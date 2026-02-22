"""Polymarket BTC feed manager — concrete FeedManager for order book collection.

Continuously discovers Polymarket BTC up/down markets for a configured interval,
collects order book snapshots via ``PolymarketDataFeed``, and publishes the
accumulated data to S3 when each market closes.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

from feedManager.FeedManager import FeedManager
from feedManager.impl.PolymarketDataFeed import PolymarketDataFeed
from feedManager.impl.polymarket_discovery import (
    get_current_btc_5m_market,
    get_current_btc_15m_market,
    get_current_btc_4h_market,
)
from dataFeed.struct.OrderBookMarketData import OrderBookMarketData

if TYPE_CHECKING:
    from dataFeed.DataFeed import DataFeed
    from dataFeed.MarketData import MarketData
    from publisher.Publisher import Publisher

logger = logging.getLogger("feedManager.polymarket")

_INITIAL_BACKOFF = 5.0
_MAX_BACKOFF = 60.0
_CLOSE_BUFFER_SECONDS = 30.0
_MIN_TIMEOUT = 60.0

_DISCOVERY_FUNCTIONS: Dict[str, Callable[[], Optional[dict]]] = {
    "5m": get_current_btc_5m_market,
    "15m": get_current_btc_15m_market,
    "4h": get_current_btc_4h_market,
}


def _parse_iso_to_epoch(iso_str: str) -> float:
    """Parse an ISO-8601 timestamp to a Unix epoch float."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.timestamp()


class PolymarketFeedManager(FeedManager):
    """Orchestrates Polymarket BTC order book collection for a single interval.

    Continuously discovers markets, creates feeds, collects order book data,
    and publishes to S3 when each market closes.

    Args:
        interval: Market interval — ``"5m"``, ``"15m"``, or ``"4h"``.
    """

    VALID_INTERVALS = {"5m", "15m", "4h"}

    def __init__(self, interval: str) -> None:
        if interval not in self.VALID_INTERVALS:
            raise ValueError(
                f"Invalid interval {interval!r}. "
                f"Must be one of {sorted(self.VALID_INTERVALS)}"
            )
        self._interval: str = interval
        self._publishers: List[Publisher] = []
        self._market_data: Optional[MarketData] = None
        self._current_feed: Optional[PolymarketDataFeed] = None
        self._stop_event: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()
        self._created: bool = False
        self._discover_fn: Callable[[], Optional[dict]] = _DISCOVERY_FUNCTIONS[interval]

    @property
    def name(self) -> str:
        """Interval-specific name used as collector_name in S3 keys."""
        return f"polymarket-btc-{self._interval}"

    def create(
        self,
        feeds: List[DataFeed],
        publishers: List[Publisher],
        market_data: MarketData,
    ) -> None:
        """Wire up publishers and market data. Feeds are created dynamically.

        Args:
            feeds: Ignored — feeds are created per-market in ``run()``.
            publishers: List of publishers to send data to.
            market_data: ``OrderBookData`` instance to accumulate snapshots.
        """
        self._publishers = list(publishers)
        self._market_data = market_data
        self._created = True

    def run(self) -> None:
        """Start the discover-collect-publish loop. Blocks until ``stop()`` is called."""
        if not self._created:
            raise RuntimeError("Must call create() before run()")

        logger.info("Starting %s feed manager", self.name)

        while not self._stop_event.is_set():
            market = self._discover_market()
            if market is None:
                break  # stopped during discovery

            feed = self._create_feed(market)
            with self._lock:
                self._current_feed = feed

            feed.start()
            logger.info("Feed started for %s", market.get("slug", "unknown"))

            self._wait_for_close(feed, market)
            self._publish(market)

            feed.stop()
            with self._lock:
                self._current_feed = None

        logger.info("%s feed manager stopped", self.name)

    def stop(self) -> None:
        """Signal the run loop to exit and stop the current feed."""
        logger.info("[%s] Stop requested", self.name)
        self._stop_event.set()
        with self._lock:
            if self._current_feed:
                self._current_feed.stop()

    # -- Internal ----------------------------------------------------------

    def _discover_market(self) -> Optional[dict]:
        """Discover the current market with exponential backoff on failure."""
        backoff = _INITIAL_BACKOFF
        logger.info("[%s] Discovering market…", self.name)
        while not self._stop_event.is_set():
            market = self._discover_fn()
            if market is not None:
                logger.info(
                    "[%s] Discovered market — slug=%s, market_id=%s, "
                    "start=%s, end=%s, tokens=%d",
                    self.name,
                    market.get("slug"),
                    market.get("market_id"),
                    market.get("event_start_time"),
                    market.get("end_date"),
                    len(market.get("token_ids", [])),
                )
                return market

            logger.warning(
                "[%s] No market found, retrying in %.0fs", self.name, backoff
            )
            self._stop_event.wait(timeout=backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)

        return None

    def _create_feed(self, market: dict) -> PolymarketDataFeed:
        """Create a PolymarketDataFeed wired to record into market_data."""
        logger.info(
            "[%s] Creating feed — slug=%s, token_ids=%s, end_date=%s",
            self.name,
            market.get("slug"),
            market["token_ids"],
            market.get("end_date"),
        )
        return PolymarketDataFeed(
            asset_ids=market["token_ids"],
            end_date=market.get("end_date"),
            on_book_update=self._on_book_update,
        )

    def _on_book_update(self, data: dict) -> None:
        """Callback: record each order book snapshot into market_data."""
        if self._market_data is not None:
            snapshot = OrderBookMarketData.from_dict(data)
            self._market_data.record(snapshot)

    def _wait_for_close(
        self, feed: PolymarketDataFeed, market: dict
    ) -> None:
        """Block until the feed closes or ``stop()`` is called."""
        end_date = market.get("end_date")
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                remaining = (end_dt - datetime.now(timezone.utc)).total_seconds()
                timeout = max(remaining + _CLOSE_BUFFER_SECONDS, _MIN_TIMEOUT)
            except (ValueError, AttributeError):
                timeout = _MIN_TIMEOUT
        else:
            timeout = _MIN_TIMEOUT

        logger.info(
            "[%s] Waiting for market close — slug=%s, timeout=%.0fs",
            self.name,
            market.get("slug"),
            timeout,
        )

        deadline = time.time() + timeout
        while not self._stop_event.is_set() and time.time() < deadline:
            if feed._closed_event.wait(timeout=1.0):
                logger.info("[%s] Market closed — slug=%s", self.name, market.get("slug"))
                return

        if self._stop_event.is_set():
            logger.info("[%s] Wait interrupted by stop signal", self.name)
        else:
            logger.warning("[%s] Wait timed out after %.0fs for slug=%s", self.name, timeout, market.get("slug"))

    def _publish(self, market: dict) -> None:
        """Export market_data and publish to all publishers."""
        if self._market_data is None:
            return

        snapshots = self._market_data.export()
        if not snapshots:
            logger.warning("No snapshots to publish for %s", market.get("slug"))
            return

        key = self._build_s3_key(market)
        payload = {
            "slug": market.get("slug", ""),
            "interval": self._interval,
            "market_id": market.get("market_id", ""),
            "event_start_time": market.get("event_start_time", ""),
            "end_date": market.get("end_date", ""),
            "snapshot_count": len(snapshots),
            "snapshots": snapshots,
        }

        for publisher in self._publishers:
            try:
                publisher.publish_json(key, payload)
                logger.info(
                    "[%s] Published %d snapshots to %s via %s",
                    self.name,
                    len(snapshots),
                    key,
                    type(publisher).__name__,
                )
            except Exception as exc:
                logger.error(
                    "[%s] Publish failed — key=%s, publisher=%s, error=%s",
                    self.name,
                    key,
                    type(publisher).__name__,
                    exc,
                )

    def _build_s3_key(self, market: dict) -> str:
        """Construct the S3 key from market metadata."""
        start_ts = _parse_iso_to_epoch(market["event_start_time"])
        end_ts = _parse_iso_to_epoch(market["end_date"])
        return f"polymarket/{self.name}/{start_ts:.6f}-{end_ts:.6f}"
