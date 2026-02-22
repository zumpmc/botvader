from __future__ import annotations

import math
import threading
import time
from typing import Dict, List, Optional

from dataFeed.DataFeed import DataFeed
from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.MarketData import MarketData
from feedManager.FeedManager import FeedManager
from publisher.Publisher import Publisher

_WINDOW_SECONDS = 300  # 5 minutes


def _next_window_boundary(now: float) -> float:
    """Return the next clean 5-minute boundary as a unix timestamp."""
    return math.ceil(now / _WINDOW_SECONDS) * _WINDOW_SECONDS


class BtcPriceFeedManager(FeedManager):
    """Concrete feed manager that orchestrates multiple BTC price feeds.

    Starts all feeds, collects ticks into a shared MarketData buffer,
    and publishes batched data to S3 every 5 minutes on clock-aligned
    windows.
    """

    def __init__(self) -> None:
        self._feeds: List[DataFeed] = []
        self._publishers: List[Publisher] = []
        self._market_data: Optional[MarketData] = None
        self._running = False
        self._flush_thread: Optional[threading.Thread] = None
        self._window_start: float = 0.0

    def create(
        self,
        feeds: List[DataFeed],
        publishers: List[Publisher],
        market_data: MarketData,
    ) -> None:
        """Wire up feeds, publishers, and market data."""
        self._feeds = list(feeds)
        self._publishers = list(publishers)
        self._market_data = market_data

    def run(self) -> None:
        """Start all feeds and the 5-minute publish loop."""
        if self._running:
            return
        self._running = True
        self._window_start = time.time()

        for feed in self._feeds:
            feed.start()

        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def stop(self) -> None:
        """Stop all feeds and flush remaining data."""
        self._running = False

        for feed in self._feeds:
            feed.stop()

        # Final flush
        self._flush()

        if self._flush_thread:
            self._flush_thread.join(timeout=5)
            self._flush_thread = None

    def health(self) -> Dict[str, FeedHealth]:
        """Return a mapping of feed name to its current health."""
        return {feed.name: feed.health() for feed in self._feeds}

    @property
    def feeds(self) -> List[DataFeed]:
        """Return the list of managed feeds."""
        return list(self._feeds)

    # -- Flush / publish -------------------------------------------------------

    def _flush_loop(self) -> None:
        """Sleep until the next 5-minute boundary, then flush."""
        while self._running:
            now = time.time()
            next_boundary = _next_window_boundary(now)
            sleep_time = next_boundary - now
            if sleep_time > 0:
                end = time.time() + sleep_time
                while self._running and time.time() < end:
                    time.sleep(min(1.0, end - time.time()))
            if self._running:
                self._flush(window_end=next_boundary)

    def _flush(self, window_end: Optional[float] = None) -> None:
        """Export market data and publish to all publishers."""
        if self._market_data is None:
            return

        data = self._market_data.export()

        if window_end is None:
            window_end = time.time()

        window_start = self._window_start
        self._window_start = window_end

        if not data:
            return

        key = f"btc-prices/all/{window_start:.6f}-{window_end:.6f}"
        for publisher in self._publishers:
            publisher.publish_json(key, data)
