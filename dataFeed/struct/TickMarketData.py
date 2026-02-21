from __future__ import annotations

import threading
from typing import List

from dataFeed.MarketData import MarketData
from dataFeed.struct.Tick import Tick


class TickMarketData(MarketData[Tick, List[dict]]):
    """Accumulates trade ticks and exports them as serialized dicts.

    On export(), the internal buffer is cleared (windowed/flush pattern),
    so each export returns only the ticks recorded since the last export.
    """

    def __init__(self) -> None:
        self._ticks: List[Tick] = []
        self._lock: threading.Lock = threading.Lock()

    def record(self, data: Tick) -> None:
        """Record a single trade tick."""
        with self._lock:
            self._ticks.append(data)

    def export(self) -> List[dict]:
        """Export all accumulated ticks as a list of dicts and clear the buffer."""
        with self._lock:
            ticks = self._ticks
            self._ticks = []
        return [tick.to_dict() for tick in ticks]
