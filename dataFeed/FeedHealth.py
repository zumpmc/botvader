from dataclasses import dataclass, asdict
from enum import Enum
import json


class FeedStatus(Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class FeedHealth:
    status: FeedStatus
    last_update: float
    message: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "FeedHealth":
        data["status"] = FeedStatus(data["status"])
        return cls(**data)
