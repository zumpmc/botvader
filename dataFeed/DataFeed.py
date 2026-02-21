class DataFeed(ABC):
    """Abstract base class for pull-based data feeds."""

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def fetch(self) -> MarketData | None:
        """Return the latest market data, or None if no data yet."""
        ...

    @abstractmethod
    def health(self) -> FeedHealth:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...