from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from dataFeed.DataFeed import DataFeed
    from dataFeed.MarketData import MarketData
    from publisher.Publisher import Publisher


class FeedManager(ABC):
    """Interface for orchestrating data feeds, market data, and publishers."""

    @abstractmethod
    def create(
        self,
        feeds: List[DataFeed],
        publishers: List[Publisher],
        market_data: MarketData,
    ) -> None:
        """Wire up feeds, publishers, and market data. Call before run()."""
        ...

    @abstractmethod
    def run(self) -> None:
        """Start the feed-to-publish loop."""
        ...
