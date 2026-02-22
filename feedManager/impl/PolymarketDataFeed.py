"""Polymarket CLOB order book feed — extends DataFeed ABC.

Streams order book snapshots from Polymarket's WebSocket API. Includes
``parse_order_book()`` for deserializing the Polymarket-specific JSON format
into ``OrderBookMarketData`` objects.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from websocket import WebSocketApp

from dataFeed.DataFeed import DataFeed
from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.struct.OrderBookMarketData import OrderBookMarketData

logger = logging.getLogger("dataFeed.polymarket")

MARKET_CHANNEL = "market"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com"

_STALE_THRESHOLD = 30.0
_DOWN_THRESHOLD = 60.0


# ---------------------------------------------------------------------------
# Polymarket JSON deserialization
# ---------------------------------------------------------------------------

def parse_order_book(ws_message: dict) -> Optional[list[OrderBookMarketData]]:
    """Parse a Polymarket WebSocket market message into OrderBookMarketData objects."""
    if isinstance(ws_message, list):
        events = ws_message
    elif isinstance(ws_message, dict) and "data" in ws_message:
        events = ws_message["data"] if isinstance(ws_message["data"], list) else [ws_message["data"]]
    else:
        events = [ws_message]

    snapshots = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type", "")
        if event_type not in ("book", "price_change", ""):
            continue

        asset_id = event.get("asset_id", "")
        if not asset_id:
            continue

        raw_bids = event.get("bids", [])
        raw_asks = event.get("asks", [])

        bids = sorted(
            [(float(b["price"]), float(b["size"])) for b in raw_bids if float(b.get("size", 0)) > 0],
            key=lambda x: x[0],
            reverse=True,
        )
        asks = sorted(
            [(float(a["price"]), float(a["size"])) for a in raw_asks if float(a.get("size", 0)) > 0],
            key=lambda x: x[0],
        )

        snap = OrderBookMarketData(
            asset_id=asset_id,
            timestamp=_parse_timestamp(event.get("timestamp", "")),
            bids=bids,
            asks=asks,
        )

        if bids:
            snap.best_bid = bids[0][0]
            snap.bid_volume = sum(s for _, s in bids)
        if asks:
            snap.best_ask = asks[0][0]
            snap.ask_volume = sum(s for _, s in asks)

        if snap.best_bid is not None and snap.best_ask is not None:
            snap.mid_price = (snap.best_bid + snap.best_ask) / 2.0
            snap.spread = snap.best_ask - snap.best_bid
            snap.weighted_mid = _weighted_mid(bids[:5], asks[:5])

        total_vol = snap.bid_volume + snap.ask_volume
        if total_vol > 0:
            snap.imbalance = (snap.bid_volume - snap.ask_volume) / total_vol

        snapshots.append(snap)

    return snapshots if snapshots else None


def _weighted_mid(bids, asks):
    """Volume-weighted mid price from top N levels."""
    if not bids or not asks:
        return None
    bid_vwap_den = sum(s for _, s in bids)
    ask_vwap_den = sum(s for _, s in asks)
    if bid_vwap_den == 0 or ask_vwap_den == 0:
        return None
    bid_top = bids[0][0]
    ask_top = asks[0][0]
    return (bid_top * ask_vwap_den + ask_top * bid_vwap_den) / (bid_vwap_den + ask_vwap_den)


def _parse_timestamp(ts_str):
    """Parse timestamp string to float epoch. Returns 0.0 if unparseable."""
    if not ts_str:
        return 0.0
    try:
        return float(ts_str)
    except (ValueError, TypeError):
        pass
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        logger.debug("Could not parse timestamp %r, returning 0.0", ts_str)
        return 0.0


# ---------------------------------------------------------------------------
# DataFeed implementation
# ---------------------------------------------------------------------------

class PolymarketDataFeed(DataFeed):
    """Polymarket CLOB order book WebSocket feed."""

    def __init__(self, asset_ids, on_book_update: Optional[Callable[[dict], None]] = None, end_date=None, on_market_closed=None):
        self.asset_ids = asset_ids
        self._on_book_update = on_book_update
        self.on_market_closed = on_market_closed
        self._ws: WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None
        self._running = False

        # DataFeed health tracking
        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._last_message_time: float = 0.0
        self._message_count = 0
        self._error_count = 0
        self._latest: OrderBookMarketData | None = None

        # Market-close machinery
        self._closed_event = threading.Event()
        self._collected_data: list = []
        self._already_closed = False
        self._close_lock = threading.Lock()

        self._end_dt: datetime | None = None
        if end_date:
            try:
                self._end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                logger.warning("Could not parse end_date: %s — will not auto-close", end_date)

    # -- DataFeed ABC ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "polymarket"

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()
        if self._end_dt:
            self._monitor_thread = threading.Thread(target=self._monitor_market_close, daemon=True)
            self._monitor_thread.start()
        self._connected.wait(timeout=10)
        logger.debug("Polymarket feed started")

    def stop(self) -> None:
        self._running = False
        if self._ws:
            self._ws.close()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._closed_event.set()
        logger.debug("Polymarket feed stopped")

    def fetch(self) -> OrderBookMarketData | None:
        with self._lock:
            return self._latest

    def health(self) -> FeedHealth:
        now = time.time()
        last = self._last_message_time
        age = now - last if last > 0 else float("inf")

        if not self._connected.is_set() or last == 0.0:
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

    # -- WebSocket callbacks ---------------------------------------------------

    def _on_open(self, _ws):
        logger.debug("Polymarket WS connected")
        self._connected.set()
        _ws.send(json.dumps({
            "assets_ids": self.asset_ids,
            "type": MARKET_CHANNEL,
        }))
        ping_thread = threading.Thread(target=self._ping, args=(_ws,), daemon=True)
        ping_thread.start()

    def _on_message(self, _ws, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        snapshots = None
        with self._lock:
            self._last_message_time = time.time()
            self._message_count += 1
            self._collected_data.append(data)

            snapshots = parse_order_book(data)
            if snapshots:
                self._latest = snapshots[-1]

        if self._on_book_update and snapshots:
            for snap in snapshots:
                try:
                    self._on_book_update(snap.to_dict())
                except Exception as e:
                    logger.error("on_book_update callback error: %s", e)

    def _on_error(self, _ws, error):
        self._error_count += 1
        logger.debug("Polymarket WS error: %s", error)

    def _on_close(self, _ws, close_status_code, _close_msg):
        logger.debug("Polymarket WS closed (code=%s)", close_status_code)
        self._connected.clear()
        if self._running:
            time.sleep(5)
            self._connect()

    # -- Internal --------------------------------------------------------------

    def _ping(self, ws):
        while self._running:
            try:
                ws.send("PING")
            except Exception:
                break
            for _ in range(10):
                if not self._running:
                    return
                time.sleep(1)

    def _connect(self):
        furl = f"{WS_URL}/ws/{MARKET_CHANNEL}"
        self._ws = WebSocketApp(
            furl,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        self._ws.run_forever()

    # -- Extra methods (beyond DataFeed ABC) -----------------------------------

    def subscribe(self, asset_ids):
        if self._ws:
            self._ws.send(json.dumps({
                "assets_ids": asset_ids,
                "operation": "subscribe",
            }))

    def unsubscribe(self, asset_ids):
        if self._ws:
            self._ws.send(json.dumps({
                "assets_ids": asset_ids,
                "operation": "unsubscribe",
            }))

    def wait_until_closed(self, timeout=None):
        """Block until the market closes. Returns collected data."""
        self._closed_event.wait(timeout=timeout)
        with self._lock:
            return list(self._collected_data)

    def _monitor_market_close(self):
        """Poll until the market end time is reached, then shut down."""
        while self._running and self._end_dt:
            now = datetime.now(timezone.utc)
            if now >= self._end_dt:
                logger.debug("Market end time reached")
                self._fire_market_closed()
                return
            time.sleep(1)

    def _fire_market_closed(self):
        """Fire on_market_closed exactly once, guarded by lock."""
        with self._close_lock:
            if self._already_closed:
                return
            self._already_closed = True
        self._running = False
        if self._ws:
            self._ws.close()
        self._closed_event.set()
        if self.on_market_closed:
            with self._lock:
                data_copy = list(self._collected_data)
            self.on_market_closed(data_copy)
