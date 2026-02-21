from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dataFeed.FeedHealth import FeedHealth


class DataFeed(ABC):
    """Abstract base class for pull-based data feeds."""

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def fetch(self) -> dict:
        """Return the latest market data, or None if no data yet."""
        ...

    @abstractmethod
    def health(self) -> FeedHealth:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...
