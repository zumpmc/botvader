import json
import time
from unittest.mock import MagicMock, patch

import pytest

from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.struct.OrderBookMarketData import OrderBookMarketData
from feedManager.impl.PolymarketDataFeed import (
    PolymarketDataFeed,
    parse_order_book,
    _weighted_mid,
    _parse_timestamp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_BOOK = {
    "event_type": "book",
    "asset_id": "abc123",
    "timestamp": "1700000000.0",
    "bids": [
        {"price": "0.55", "size": "100"},
        {"price": "0.50", "size": "200"},
    ],
    "asks": [
        {"price": "0.60", "size": "150"},
        {"price": "0.65", "size": "80"},
    ],
}

SAMPLE_MESSAGE = json.dumps(SAMPLE_BOOK)

ASSET_IDS = ["abc123"]


def _simulate_message(feed, raw=SAMPLE_MESSAGE):
    """Call the internal _on_message handler directly."""
    feed._on_message(None, raw)


# ---------------------------------------------------------------------------
# name
# ---------------------------------------------------------------------------

def test_name():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    print(f"  feed.name = {feed.name!r}")
    assert feed.name == "polymarket"


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def test_fetch_returns_none_before_any_data():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    result = feed.fetch()
    print(f"  fetch() before data = {result}")
    assert result is None


def test_fetch_returns_latest_snapshot():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    _simulate_message(feed)
    snap = feed.fetch()
    print(f"  fetch() = {snap}")
    assert snap is not None
    assert isinstance(snap, OrderBookMarketData)
    assert snap.asset_id == "abc123"
    assert snap.best_bid == 0.55
    assert snap.best_ask == 0.60


def test_fetch_returns_most_recent_message():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    _simulate_message(feed)
    second = json.dumps({
        "event_type": "book",
        "asset_id": "abc123",
        "timestamp": "1700000001.0",
        "bids": [{"price": "0.70", "size": "50"}],
        "asks": [{"price": "0.75", "size": "60"}],
    })
    _simulate_message(feed, second)
    snap = feed.fetch()
    print(f"  first best_bid=0.55, second best_bid=0.70")
    print(f"  fetch() returned best_bid={snap.best_bid} (should be latest)")
    assert snap.best_bid == 0.70


# ---------------------------------------------------------------------------
# on_book_update callback
# ---------------------------------------------------------------------------

def test_on_book_update_callback_fires():
    cb = MagicMock()
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS, on_book_update=cb)
    _simulate_message(feed)
    cb.assert_called_once()
    tick = cb.call_args[0][0]
    print(f"  on_book_update called with: {tick}")
    assert tick["asset_id"] == "abc123"
    assert tick["best_bid"] == 0.55
    assert tick["best_ask"] == 0.60
    assert tick["mid_price"] == pytest.approx(0.575)
    assert "bids" in tick
    assert "asks" in tick


def test_on_book_update_not_required():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    _simulate_message(feed)  # should not raise
    print(f"  no callback set — no crash")


def test_on_book_update_not_called_for_unparseable():
    cb = MagicMock()
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS, on_book_update=cb)
    # Message with no asset_id — parse_order_book returns None
    msg = json.dumps({"event_type": "book", "bids": [], "asks": []})
    _simulate_message(feed, msg)
    cb.assert_not_called()
    print(f"  callback not fired for unparseable message")


# ---------------------------------------------------------------------------
# parse_order_book
# ---------------------------------------------------------------------------

def test_parse_order_book_valid():
    result = parse_order_book(SAMPLE_BOOK)
    assert result is not None
    assert len(result) == 1
    snap = result[0]
    print(f"  parsed: asset={snap.asset_id}, bids={len(snap.bids)}, asks={len(snap.asks)}")
    assert snap.asset_id == "abc123"
    assert snap.best_bid == 0.55
    assert snap.best_ask == 0.60
    assert snap.mid_price == pytest.approx(0.575)
    assert snap.spread == pytest.approx(0.05)
    assert snap.bid_volume == pytest.approx(300.0)
    assert snap.ask_volume == pytest.approx(230.0)
    assert snap.imbalance is not None


def test_parse_order_book_with_data_wrapper():
    wrapped = {"data": [SAMPLE_BOOK]}
    result = parse_order_book(wrapped)
    assert result is not None
    assert len(result) == 1
    assert result[0].asset_id == "abc123"


def test_parse_order_book_list_input():
    result = parse_order_book([SAMPLE_BOOK])
    assert result is not None
    assert len(result) == 1


def test_parse_order_book_no_asset_id():
    msg = {"event_type": "book", "bids": [], "asks": []}
    result = parse_order_book(msg)
    print(f"  result for missing asset_id = {result}")
    assert result is None


def test_parse_order_book_empty_book():
    msg = {"event_type": "book", "asset_id": "x", "bids": [], "asks": []}
    result = parse_order_book(msg)
    assert result is not None
    snap = result[0]
    assert snap.best_bid is None
    assert snap.best_ask is None
    assert snap.mid_price is None


def test_parse_order_book_filters_zero_size():
    msg = {
        "event_type": "book",
        "asset_id": "x",
        "bids": [{"price": "0.5", "size": "0"}, {"price": "0.4", "size": "10"}],
        "asks": [{"price": "0.6", "size": "5"}],
    }
    result = parse_order_book(msg)
    snap = result[0]
    assert len(snap.bids) == 1
    assert snap.bids[0] == (0.4, 10.0)


def test_parse_order_book_ignores_unknown_event_type():
    msg = {"event_type": "trade", "asset_id": "x", "bids": [], "asks": []}
    result = parse_order_book(msg)
    assert result is None


# ---------------------------------------------------------------------------
# _weighted_mid
# ---------------------------------------------------------------------------

def test_weighted_mid_basic():
    bids = [(0.50, 100)]
    asks = [(0.60, 100)]
    result = _weighted_mid(bids, asks)
    assert result == pytest.approx(0.55)


def test_weighted_mid_empty():
    assert _weighted_mid([], [(0.6, 10)]) is None
    assert _weighted_mid([(0.5, 10)], []) is None


def test_weighted_mid_zero_volume():
    assert _weighted_mid([(0.5, 0)], [(0.6, 10)]) is None


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------

def test_parse_timestamp_float_string():
    assert _parse_timestamp("1700000000.0") == 1700000000.0


def test_parse_timestamp_iso():
    result = _parse_timestamp("2023-11-14T22:13:20Z")
    assert result > 0


def test_parse_timestamp_empty():
    assert _parse_timestamp("") == 0.0
    assert _parse_timestamp(None) == 0.0


def test_parse_timestamp_garbage():
    assert _parse_timestamp("not-a-date") == 0.0


def test_parse_timestamp_milliseconds_converted_to_seconds():
    """Timestamps above 1e10 are assumed to be milliseconds and divided by 1000."""
    ms_ts = "1700000000000"
    result = _parse_timestamp(ms_ts)
    assert result == pytest.approx(1700000000.0)


def test_parse_timestamp_milliseconds_with_decimals():
    """Millisecond timestamps with sub-ms precision are converted correctly."""
    ms_ts = "1700000000123.456"
    result = _parse_timestamp(ms_ts)
    assert result == pytest.approx(1700000000.123456, rel=1e-6)


def test_parse_timestamp_seconds_not_converted():
    """Timestamps already in seconds (below 1e10) are returned as-is."""
    assert _parse_timestamp("1700000000.0") == 1700000000.0
    assert _parse_timestamp("1700000000") == 1700000000.0


def test_parse_timestamp_iso_not_affected_by_ms_check():
    """ISO timestamps go through fromisoformat, not the ms conversion path."""
    result = _parse_timestamp("2023-11-14T22:13:20Z")
    assert result > 1_000_000_000
    assert result < 2_000_000_000


def test_parse_order_book_normalizes_ms_timestamp():
    """parse_order_book produces seconds-precision timestamps from ms input."""
    event_ms = {
        "event_type": "book",
        "asset_id": "abc123",
        "timestamp": "1700000000000",
        "bids": [{"price": "0.55", "size": "100"}],
        "asks": [{"price": "0.60", "size": "150"}],
    }
    result = parse_order_book(event_ms)
    assert result is not None
    snap = result[0]
    assert snap.timestamp == pytest.approx(1700000000.0)


# ---------------------------------------------------------------------------
# health — before start (DOWN)
# ---------------------------------------------------------------------------

def test_health_down_before_start():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    h = feed.health()
    print(f"  health = {h.status.value}, last_update={h.last_update}, msg={h.message!r}")
    assert h.status == FeedStatus.DOWN
    assert h.last_update == 0.0


# ---------------------------------------------------------------------------
# health — OK
# ---------------------------------------------------------------------------

def test_health_ok_when_connected_and_fresh():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._connected.set()
    _simulate_message(feed)
    h = feed.health()
    print(f"  health = {h.status.value}, last_update={h.last_update:.2f}, msg={h.message!r}")
    assert h.status == FeedStatus.OK
    assert "msgs=1" in h.message
    assert h.last_update > 0


# ---------------------------------------------------------------------------
# health — DEGRADED (stale data 30-60s)
# ---------------------------------------------------------------------------

def test_health_degraded_when_stale():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._connected.set()
    _simulate_message(feed)
    feed._last_message_time = time.time() - 45
    h = feed.health()
    print(f"  health = {h.status.value}, msg={h.message!r}")
    assert h.status == FeedStatus.DEGRADED
    assert "stale" in h.message


# ---------------------------------------------------------------------------
# health — DOWN (data older than 60s)
# ---------------------------------------------------------------------------

def test_health_down_when_data_too_old():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._connected.set()
    _simulate_message(feed)
    feed._last_message_time = time.time() - 90
    h = feed.health()
    print(f"  health = {h.status.value}, msg={h.message!r}")
    assert h.status == FeedStatus.DOWN
    assert "no data" in h.message


# ---------------------------------------------------------------------------
# _on_error
# ---------------------------------------------------------------------------

def test_on_error_increments_count():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._on_error(None, Exception("timeout"))
    print(f"  error_count after 1 error: {feed._error_count}")
    assert feed._error_count == 1


# ---------------------------------------------------------------------------
# _on_close
# ---------------------------------------------------------------------------

def test_on_close_clears_connected():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._connected.set()
    feed._on_close(None, 1000, "normal")
    print(f"  connected={feed._connected.is_set()} after close(1000)")
    assert not feed._connected.is_set()


# ---------------------------------------------------------------------------
# _on_message — malformed JSON
# ---------------------------------------------------------------------------

def test_on_message_ignores_bad_json():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._on_message(None, "not json {{{")
    print(f"  fetch after bad json = {feed.fetch()}, msg_count={feed._message_count}")
    assert feed.fetch() is None
    assert feed._message_count == 0


# ---------------------------------------------------------------------------
# start / stop (mocked — no real WS)
# ---------------------------------------------------------------------------

@patch("feedManager.impl.PolymarketDataFeed.WebSocketApp")
def test_start_stop_lifecycle(mock_ws_cls):
    mock_app = MagicMock()
    mock_app.run_forever = MagicMock(side_effect=lambda: time.sleep(0.1))
    mock_ws_cls.return_value = mock_app

    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._connected.set()  # simulate connection
    feed.start()
    time.sleep(0.3)
    feed.stop()

    print(f"  running={feed._running}, ws created={mock_ws_cls.called}")
    assert not feed._running
    mock_ws_cls.assert_called()


def test_start_is_idempotent():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    with patch.object(feed, "_connect"):
        feed._connected.set()
        feed.start()
        thread1 = feed._thread
        feed.start()
        print(f"  same thread after double start: {feed._thread is thread1}")
        assert feed._thread is thread1
        feed._running = False


# ---------------------------------------------------------------------------
# market close
# ---------------------------------------------------------------------------

def test_fire_market_closed_fires_callback_once():
    cb = MagicMock()
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS, on_market_closed=cb)
    feed._running = True
    with feed._lock:
        feed._collected_data = [{"some": "data"}]
    feed._fire_market_closed()
    feed._fire_market_closed()  # second call should be no-op
    cb.assert_called_once()
    assert not feed._running
    assert feed._closed_event.is_set()


def test_fire_market_closed_without_callback():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._running = True
    feed._fire_market_closed()
    assert not feed._running
    assert feed._closed_event.is_set()


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------

def test_subscribe_sends_message():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._ws = MagicMock()
    feed.subscribe(["def456"])
    feed._ws.send.assert_called_once()
    payload = json.loads(feed._ws.send.call_args[0][0])
    assert payload["assets_ids"] == ["def456"]
    assert payload["operation"] == "subscribe"


def test_unsubscribe_sends_message():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed._ws = MagicMock()
    feed.unsubscribe(["abc123"])
    feed._ws.send.assert_called_once()
    payload = json.loads(feed._ws.send.call_args[0][0])
    assert payload["assets_ids"] == ["abc123"]
    assert payload["operation"] == "unsubscribe"


def test_subscribe_noop_without_ws():
    feed = PolymarketDataFeed(asset_ids=ASSET_IDS)
    feed.subscribe(["x"])  # should not raise
    feed.unsubscribe(["x"])  # should not raise
