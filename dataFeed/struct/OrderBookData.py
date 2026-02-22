from __future__ import annotations

import threading
from typing import List

from dataFeed.MarketData import MarketData
from dataFeed.struct.OrderBookMarketData import OrderBookMarketData


class OrderBookData(MarketData[OrderBookMarketData, List[dict]]):
    """Accumulates order book snapshots and exports them as serialized dicts.

    On export(), the internal buffer is cleared (windowed/flush pattern),
    so each export returns only the snapshots recorded since the last export.
    """

    def __init__(self) -> None:
        self._snapshots: List[OrderBookMarketData] = []
        self._lock: threading.Lock = threading.Lock()

    def record(self, data: OrderBookMarketData) -> None:
        """Record a single order book snapshot."""
        with self._lock:
            self._snapshots.append(data)

    def export(self) -> List[dict]:
        """Export all accumulated snapshots as a list of dicts and clear the buffer."""
        with self._lock:
            snapshots = self._snapshots
            self._snapshots = []
        return [snap.to_dict() for snap in snapshots]
