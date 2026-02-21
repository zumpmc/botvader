from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")


class MarketData(ABC, Generic[T, E]):
    """Interface for accumulating and exporting market data.

    Type Parameters:
        T: The type of data accepted by record().
        E: The type of data returned by export().
    """

    @abstractmethod
    def record(self, data: T) -> None:
        """Record incoming data from a feed."""
        ...

    @abstractmethod
    def export(self) -> E:
        """Export the accumulated market data for publishing."""
        ...
