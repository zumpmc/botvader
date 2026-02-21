import json
import threading
import time
from typing import Callable, Optional

import websocket

from dataFeed.DataFeed import DataFeed
from dataFeed.FeedHealth import FeedHealth, FeedStatus

_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@trade"
_STALE_THRESHOLD = 30.0
_DOWN_THRESHOLD = 60.0


class BinanceDataFeed(DataFeed):

    def __init__(self, on_tick: Optional[Callable[[dict], None]] = None):
        self._on_tick = on_tick
        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False
        self._connected = False
        self._geo_blocked = False
        self._last_data: Optional[dict] = None
        self._last_message_time: float = 0.0
        self._message_count: int = 0
        self._error_count: int = 0

    @property
    def name(self) -> str:
        return "binance-btc-usd"

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._ws:
            self._ws.close()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def fetch(self) -> Optional[dict]:
        with self._lock:
            return self._last_data

    def health(self) -> FeedHealth:
        now = time.time()
        last = self._last_message_time
        age = now - last if last > 0 else float("inf")

        if self._geo_blocked:
            return FeedHealth(
                status=FeedStatus.DOWN,
                last_update=last,
                message="geo-blocked",
            )

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

    # -- WebSocket internals --------------------------------------------------

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

    def _on_message(self, ws, message: str) -> None:
        try:
            raw = json.loads(message)
        except json.JSONDecodeError:
            return

        tick = {
            "timestamp": float(raw.get("T", 0)) / 1000.0,
            "price": float(raw.get("p", 0)),
            "source": "binance",
        }

        with self._lock:
            self._last_data = tick
            self._last_message_time = time.time()
            self._message_count += 1

        if self._on_tick:
            self._on_tick(tick)

    def _on_error(self, ws, error) -> None:
        self._error_count += 1
        if isinstance(error, Exception):
            msg = str(error).lower()
            if "451" in msg or "restricted" in msg or "forbidden" in msg:
                self._geo_blocked = True

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self._connected = False
        if close_status_code == 451:
            self._geo_blocked = True
