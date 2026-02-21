from dataclasses import dataclass
from typing import Optional
import json


@dataclass
class Tick:
    """A single market trade tick.

    Parameters:
        timestamp: Unix epoch timestamp of the trade.
        price: Trade price.
        source: Exchange name (e.g. "coinbase", "binance", "kraken").
        size: Trade quantity (optional; not all exchanges provide this).
        side: Trade side, e.g. "BUY" or "SELL" (optional).
    """

    timestamp: float
    price: float
    source: str
    size: Optional[float] = None
    side: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary. All fields are included."""
        return {
            "timestamp": self.timestamp,
            "price": self.price,
            "source": self.source,
            "size": self.size,
            "side": self.side,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "Tick":
        """Reconstruct a Tick from a dictionary."""
        return cls(
            timestamp=float(data["timestamp"]),
            price=float(data["price"]),
            source=str(data["source"]),
            size=float(data["size"]) if data.get("size") is not None else None,
            side=str(data["side"]) if data.get("side") is not None else None,
        )
