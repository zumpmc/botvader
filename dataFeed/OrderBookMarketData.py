from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrderBookMarketData:
    """Snapshot of an order book at a point in time."""

    asset_id: str
    timestamp: float
    bids: list[tuple[float, float]] = field(default_factory=list)  # (price, size) desc
    asks: list[tuple[float, float]] = field(default_factory=list)  # (price, size) asc
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid_price: Optional[float] = None
    spread: Optional[float] = None
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    weighted_mid: Optional[float] = None
    imbalance: Optional[float] = None
