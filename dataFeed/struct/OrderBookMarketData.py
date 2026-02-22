from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrderBookMarketData:
    """Snapshot of an order book at a point in time.

    Parameters:
        asset_id: Identifier for the traded asset.
        timestamp: Unix epoch timestamp of the snapshot.
        bids: List of (price, size) tuples sorted descending by price.
        asks: List of (price, size) tuples sorted ascending by price.
        best_bid: Highest bid price (optional).
        best_ask: Lowest ask price (optional).
        mid_price: Midpoint of best bid and best ask (optional).
        spread: Difference between best ask and best bid (optional).
        bid_volume: Total size across all bid levels.
        ask_volume: Total size across all ask levels.
        weighted_mid: Volume-weighted mid price (optional).
        imbalance: (bid_volume - ask_volume) / total_volume (optional).
    """

    asset_id: str
    timestamp: float
    bids: list[tuple[float, float]] = field(default_factory=list)
    asks: list[tuple[float, float]] = field(default_factory=list)
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid_price: Optional[float] = None
    spread: Optional[float] = None
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    weighted_mid: Optional[float] = None
    imbalance: Optional[float] = None

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary.

        Tuples in bids/asks are converted to [price, size] lists for
        JSON compatibility.
        """
        return {
            "asset_id": self.asset_id,
            "timestamp": self.timestamp,
            "bids": [[p, s] for p, s in self.bids],
            "asks": [[p, s] for p, s in self.asks],
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": self.mid_price,
            "spread": self.spread,
            "bid_volume": self.bid_volume,
            "ask_volume": self.ask_volume,
            "weighted_mid": self.weighted_mid,
            "imbalance": self.imbalance,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "OrderBookMarketData":
        """Reconstruct an OrderBookMarketData from a dictionary.

        Accepts bids/asks as lists of [price, size] pairs and converts
        them back to tuples.
        """
        return cls(
            asset_id=str(data["asset_id"]),
            timestamp=float(data["timestamp"]),
            bids=[(float(p), float(s)) for p, s in data.get("bids", [])],
            asks=[(float(p), float(s)) for p, s in data.get("asks", [])],
            best_bid=float(data["best_bid"]) if data.get("best_bid") is not None else None,
            best_ask=float(data["best_ask"]) if data.get("best_ask") is not None else None,
            mid_price=float(data["mid_price"]) if data.get("mid_price") is not None else None,
            spread=float(data["spread"]) if data.get("spread") is not None else None,
            bid_volume=float(data.get("bid_volume", 0.0)),
            ask_volume=float(data.get("ask_volume", 0.0)),
            weighted_mid=float(data["weighted_mid"]) if data.get("weighted_mid") is not None else None,
            imbalance=float(data["imbalance"]) if data.get("imbalance") is not None else None,
        )
