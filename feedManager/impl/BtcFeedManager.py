"""BTC feed manager — concrete FeedManager for multi-exchange tick collection.

Orchestrates Binance, Kraken, Coinbase, and Chainlink data feeds, collecting
full-fidelity websocket tick data and publishing batched ticks to S3 on
5-minute clock-aligned windows.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Dict, List, Optional, TYPE_CHECKING

from feedManager.FeedManager import FeedManager
from dataFeed.struct.Tick import Tick

if TYPE_CHECKING:
    from dataFeed.DataFeed import DataFeed
    from dataFeed.MarketData import MarketData
    from dataFeed.struct.TickMarketData import TickMarketData
    from publisher.Publisher import Publisher

logger = logging.getLogger("feedManager.btc")

_WINDOW_SECONDS = 300  # 5 minutes


def _next_window_boundary(now: float) -> float:
    """Return the next clean 5-minute boundary as a unix timestamp."""
    return math.ceil(now / _WINDOW_SECONDS) * _WINDOW_SECONDS


class BtcFeedManager(FeedManager):
    """Orchestrates multiple BTC data feeds and publishes ticks to S3.

    Starts all feeds, collects ticks via ``on_tick`` callbacks into a
    ``TickMarketData`` accumulator, and publishes batched ticks to S3
    every 5 minutes on clean clock-aligned windows. Ticks are grouped
    by exchange source and published under separate S3 keys.
    """

    def __init__(self) -> None:
        self._feeds: List[DataFeed] = []
        self._publishers: List[Publisher] = []
        self._market_data: Optional[TickMarketData] = None
        self._stop_event: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()
        self._created: bool = False
        self._window_start: float = 0.0

    @property
    def name(self) -> str:
        """Manager name used in the dashboard and S3 keys."""
        return "btc-data"

    def create(
        self,
        feeds: List[DataFeed],
        publishers: List[Publisher],
        market_data: MarketData,
    ) -> None:
        """Wire up feeds, publishers, and market data.

        Args:
            feeds: BTC data feeds to orchestrate.
            publishers: Publishers for S3 output.
            market_data: ``TickMarketData`` instance to accumulate ticks.
        """
        self._feeds = list(feeds)
        self._publishers = list(publishers)
        self._market_data = market_data
        self._created = True

    def run(self) -> None:
        """Start all feeds and run the flush loop. Blocks until ``stop()``."""
        if not self._created:
            raise RuntimeError("Must call create() before run()")

        logger.info("Starting %s feed manager with %d feeds", self.name, len(self._feeds))

        self._window_start = time.time()

        # Wire on_tick callbacks
        for feed in self._feeds:
            feed._on_tick = self._on_tick

        # Start all feeds
        for feed in self._feeds:
            feed.start()

        logger.info("All feeds started")

        # Run flush loop until stopped
        self._flush_loop()

        # Final flush on shutdown
        self._flush()

        # Stop all feeds
        for feed in self._feeds:
            feed.stop()

        logger.info("%s feed manager stopped", self.name)

    def stop(self) -> None:
        """Signal the run loop to exit."""
        self._stop_event.set()

    # -- Internal --------------------------------------------------------------

    def _on_tick(self, tick_dict: dict) -> None:
        """Callback: record each tick into market_data."""
        if self._market_data is not None:
            tick = Tick.from_dict(tick_dict)
            self._market_data.record(tick)

    def _flush_loop(self) -> None:
        """Sleep until the next 5-minute boundary, then flush."""
        while not self._stop_event.is_set():
            now = time.time()
            next_boundary = _next_window_boundary(now)
            # Sleep in small increments so we can check _stop_event
            while not self._stop_event.is_set() and time.time() < next_boundary:
                remaining = next_boundary - time.time()
                self._stop_event.wait(timeout=min(1.0, max(0, remaining)))
            if not self._stop_event.is_set():
                self._flush(window_end=next_boundary)

    def _flush(self, window_end: Optional[float] = None) -> None:
        """Export accumulated ticks, group by source, and publish to S3."""
        if self._market_data is None:
            return

        ticks = self._market_data.export()

        if window_end is None:
            window_end = time.time()

        with self._lock:
            window_start = self._window_start
            self._window_start = window_end

        if not ticks:
            return

        # Group ticks by exchange source
        by_source: Dict[str, list] = {}
        for tick in ticks:
            source = tick.get("source", "unknown")
            by_source.setdefault(source, []).append(tick)

        # Publish each source separately
        for source, source_ticks in by_source.items():
            feed_name = f"{source}-btc-usd"
            key = f"{source}/{feed_name}/{window_start:.6f}-{window_end:.6f}"

            for pub in self._publishers:
                try:
                    pub.publish_json(key, source_ticks)
                except Exception as exc:
                    logger.error("Publish failed for %s: %s", key, exc)

            logger.info(
                "Published %d ticks to %s", len(source_ticks), key
            )
