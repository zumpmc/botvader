from abc import ABC, abstractmethod


class Publisher(ABC):
    """Abstract base class for publishing data."""

    @abstractmethod
    def publish(self, key: str, data: bytes) -> None:
        """Publish data to the given key/path."""
        ...

    @abstractmethod
    def publish_json(self, key: str, obj: dict) -> None:
        """Serialize a dict as JSON and publish it."""
        ...

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Retrieve data by key/path."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete data at the given key/path."""
        ...

    @abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """List available keys under prefix."""
        ...
