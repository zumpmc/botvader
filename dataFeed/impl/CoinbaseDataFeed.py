import json
import math
import threading
import time
from datetime import datetime
from typing import Callable, List, Optional

import websocket

from dataFeed.DataFeed import DataFeed
from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.struct.Tick import Tick
from publisher.Publisher import Publisher

_WS_URL = "wss://advanced-trade-ws.coinbase.com"
_STALE_THRESHOLD = 30.0
_DOWN_THRESHOLD = 60.0
_WINDOW_SECONDS = 300  # 5 minutes


def _parse_coinbase_timestamp(ts_str: str) -> float:
    """Parse a Coinbase ISO-8601 timestamp to a unix epoch float."""
    if not ts_str:
        return time.time()
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return time.time()


def _next_window_boundary(now: float) -> float:
    """Return the next clean 5-minute boundary as a unix timestamp."""
    return math.ceil(now / _WINDOW_SECONDS) * _WINDOW_SECONDS


class CoinbaseDataFeed(DataFeed):
    """Streams BTC-USD trades from Coinbase and publishes batched ticks to S3
    every 5 minutes on clean clock-aligned windows."""

    def __init__(
        self,
        publisher: Optional[Publisher] = None,
        on_tick: Optional[Callable[[dict], None]] = None,
    ):
        self._publisher = publisher
        self._on_tick = on_tick
        self._ws: Optional[websocket.WebSocketApp] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._flush_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False
        self._connected = False
        self._last_data: Optional[dict] = None
        self._last_message_time: float = 0.0
        self._message_count: int = 0
        self._error_count: int = 0

        # Batching state
        self._buffer: List[Tick] = []
        self._window_start: float = 0.0

    @property
    def name(self) -> str:
        return "coinbase-btc-usd"

    # -- Lifecycle -------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        now = time.time()
        self._window_start = now

        self._ws_thread = threading.Thread(target=self._connect, daemon=True)
        self._ws_thread.start()

        if self._publisher:
            self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._flush_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._ws:
            self._ws.close()
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
            self._ws_thread = None
        # Flush any remaining ticks
        if self._publisher:
            self._flush()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)
            self._flush_thread = None

    # -- DataFeed interface ----------------------------------------------------

    def fetch(self) -> Optional[dict]:
        with self._lock:
            return self._last_data

    def health(self) -> FeedHealth:
        now = time.time()
        last = self._last_message_time
        age = now - last if last > 0 else float("inf")

        if not self._connected or last == 0.0:
            return FeedHealth(
                status=FeedStatus.DOWN,
                last_update=last,
                message=f"disconnected, errors={self._error_count}",
            )

        if age > _DOWN_THRESHOLD:
            return FeedHealth(
                status=FeedStatus.DOWN,
                last_update=last,
                message=f"no data ({age:.0f}s), msgs={self._message_count}, errors={self._error_count}",
            )

        if age > _STALE_THRESHOLD:
            return FeedHealth(
                status=FeedStatus.DEGRADED,
                last_update=last,
                message=f"stale data ({age:.0f}s), msgs={self._message_count}, errors={self._error_count}",
            )

        return FeedHealth(
            status=FeedStatus.OK,
            last_update=last,
            message=f"msgs={self._message_count}, errors={self._error_count}",
        )

    # -- Flush / publish -------------------------------------------------------

    def _flush_loop(self) -> None:
        """Sleep until the next 5-minute boundary, then flush."""
        while self._running:
            now = time.time()
            next_boundary = _next_window_boundary(now)
            sleep_time = next_boundary - now
            if sleep_time > 0:
                # Wake up periodically so we can check _running
                end = time.time() + sleep_time
                while self._running and time.time() < end:
                    time.sleep(min(1.0, end - time.time()))
            if self._running:
                self._flush(window_end=next_boundary)

    def _flush(self, window_end: Optional[float] = None) -> None:
        """Swap the buffer and publish it to S3."""
        with self._lock:
            ticks = self._buffer
            self._buffer = []
            window_start = self._window_start

        if window_end is None:
            window_end = time.time()

        # Update window_start for the next window
        with self._lock:
            self._window_start = window_end

        if not ticks:
            return

        key = f"coinbase/{self.name}/{window_start:.6f}-{window_end:.6f}"
        self._publisher.publish_json(key, [t.to_dict() for t in ticks])

    # -- WebSocket internals ---------------------------------------------------

    def _connect(self) -> None:
        while self._running:
            self._ws = websocket.WebSocketApp(
                _WS_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self._ws.run_forever()
            if self._running:
                time.sleep(5)

    def _on_open(self, ws) -> None:
        self._connected = True
        subscribe_msg = json.dumps({
            "type": "subscribe",
            "channel": "market_trades",
            "product_ids": ["BTC-USD"],
        })
        ws.send(subscribe_msg)

    def _on_message(self, ws, message: str) -> None:
        try:
            raw = json.loads(message)
        except json.JSONDecodeError:
            return

        channel = raw.get("channel")
        if channel != "market_trades":
            return

        events = raw.get("events", [])
        for event in events:
            trades = event.get("trades", [])
            for trade in trades:
                tick = Tick(
                    timestamp=_parse_coinbase_timestamp(trade.get("time", "")),
                    price=float(trade.get("price", 0)),
                    size=float(trade.get("size", 0)),
                    side=trade.get("side", ""),
                    source="coinbase",
                )

                with self._lock:
                    self._last_data = tick.to_dict()
                    self._last_message_time = time.time()
                    self._message_count += 1
                    self._buffer.append(tick)

                if self._on_tick:
                    self._on_tick(tick.to_dict())

    def _on_error(self, ws, error) -> None:
        self._error_count += 1

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self._connected = False
