import math
import os
import threading
import time
from typing import Callable, List, Optional

from web3 import Web3

from dataFeed.DataFeed import DataFeed
from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.struct.Tick import Tick
from publisher.Publisher import Publisher

_BTC_USD_ADDRESS = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"
_DECIMALS = 8
_STALE_THRESHOLD = 90.0
_DOWN_THRESHOLD = 300.0
_WINDOW_SECONDS = 300  # 5 minutes

# Minimal ABI — only latestRoundData()
_AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


def _next_window_boundary(now: float) -> float:
    """Return the next clean 5-minute boundary as a unix timestamp."""
    return math.ceil(now / _WINDOW_SECONDS) * _WINDOW_SECONDS


class ChainlinkDataFeed(DataFeed):
    """Polls Chainlink BTC/USD oracle on Ethereum mainnet and publishes
    batched ticks to S3 every 5 minutes on clean clock-aligned windows."""

    def __init__(
        self,
        publisher: Optional[Publisher] = None,
        on_tick: Optional[Callable[[dict], None]] = None,
        poll_interval: float = 10.0,
    ):
        self._publisher = publisher
        self._on_tick = on_tick
        self._poll_interval = poll_interval

        rpc_url = os.environ.get("ETH_RPC_URL", "")
        self._w3 = Web3(Web3.HTTPProvider(rpc_url)) if rpc_url else None
        self._contract = None
        if self._w3:
            self._contract = self._w3.eth.contract(
                address=Web3.to_checksum_address(_BTC_USD_ADDRESS),
                abi=_AGGREGATOR_ABI,
            )

        self._poll_thread: Optional[threading.Thread] = None
        self._flush_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False
        self._last_data: Optional[dict] = None
        self._last_message_time: float = 0.0
        self._message_count: int = 0
        self._error_count: int = 0
        self._last_round_id: int = 0

        # Batching state
        self._buffer: List[Tick] = []
        self._window_start: float = 0.0

    @property
    def name(self) -> str:
        return "chainlink-btc-usd"

    # -- Lifecycle -------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        now = time.time()
        self._window_start = now

        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

        if self._publisher:
            self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._flush_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=15)
            self._poll_thread = None
        if self._publisher:
            self._flush()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)
            self._flush_thread = None

    # -- DataFeed interface ----------------------------------------------------

    def fetch(self) -> Optional[dict]:
        with self._lock:
            return self._last_data

    def health(self) -> FeedHealth:
        if not self._w3 or not self._contract:
            return FeedHealth(
                status=FeedStatus.DOWN,
                last_update=0.0,
                message="no ETH_RPC_URL configured",
            )

        now = time.time()
        last = self._last_message_time
        age = now - last if last > 0 else float("inf")

        if last == 0.0:
            return FeedHealth(
                status=FeedStatus.DOWN,
                last_update=last,
                message=f"no data yet, errors={self._error_count}",
            )

        if age > _DOWN_THRESHOLD:
            return FeedHealth(
                status=FeedStatus.DOWN,
                last_update=last,
                message=f"no update ({age:.0f}s), rounds={self._message_count}, errors={self._error_count}",
            )

        if age > _STALE_THRESHOLD:
            return FeedHealth(
                status=FeedStatus.DEGRADED,
                last_update=last,
                message=f"stale ({age:.0f}s), rounds={self._message_count}, errors={self._error_count}",
            )

        return FeedHealth(
            status=FeedStatus.OK,
            last_update=last,
            message=f"rounds={self._message_count}, errors={self._error_count}",
        )

    # -- Polling ---------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Poll latestRoundData() every N seconds."""
        while self._running:
            try:
                self._poll_once()
            except Exception:
                self._error_count += 1

            # Sleep in small increments so we can check _running
            end = time.time() + self._poll_interval
            while self._running and time.time() < end:
                time.sleep(min(1.0, end - time.time()))

    def _poll_once(self) -> None:
        if not self._contract:
            return

        result = self._contract.functions.latestRoundData().call()
        round_id, answer, started_at, updated_at, answered_in_round = result

        # Only record if this is a new round
        if round_id == self._last_round_id:
            return
        self._last_round_id = round_id

        price = answer / (10 ** _DECIMALS)
        tick = Tick(
            timestamp=float(updated_at),
            price=price,
            source="chainlink",
        )

        with self._lock:
            self._last_data = tick.to_dict()
            self._last_message_time = time.time()
            self._message_count += 1
            self._buffer.append(tick)

        if self._on_tick:
            self._on_tick(tick.to_dict())

    # -- Flush / publish -------------------------------------------------------

    def _flush_loop(self) -> None:
        """Sleep until the next 5-minute boundary, then flush."""
        while self._running:
            now = time.time()
            next_boundary = _next_window_boundary(now)
            sleep_time = next_boundary - now
            if sleep_time > 0:
                end = time.time() + sleep_time
                while self._running and time.time() < end:
                    time.sleep(min(1.0, end - time.time()))
            if self._running:
                self._flush(window_end=next_boundary)

    def _flush(self, window_end: Optional[float] = None) -> None:
        """Swap the buffer and publish it to S3."""
        with self._lock:
            ticks = self._buffer
            self._buffer = []
            window_start = self._window_start

        if window_end is None:
            window_end = time.time()

        with self._lock:
            self._window_start = window_end

        if not ticks:
            return

        key = f"chainlink/{self.name}/{window_start:.6f}-{window_end:.6f}"
        self._publisher.publish_json(key, [t.to_dict() for t in ticks])
