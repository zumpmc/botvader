import json
import threading
import time
from unittest.mock import patch, MagicMock, call

import pytest

from feedManager.impl.PolymarketFeedManager import (
    PolymarketFeedManager,
    _parse_iso_to_epoch,
    _INITIAL_BACKOFF,
    _MAX_BACKOFF,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_market(
    slug="btc-updown-5m-1700000000",
    token_ids=None,
    end_date="2023-11-14T22:18:20Z",
    event_start_time="2023-11-14T22:13:20Z",
):
    """Build a minimal discovery market dict."""
    return {
        "url": f"https://polymarket.com/event/{slug}",
        "title": "BTC Up/Down 5m",
        "slug": slug,
        "market_id": "market-1",
        "condition_id": "cond-1",
        "question_id": "q-1",
        "token_ids": token_ids or ["token-yes", "token-no"],
        "outcomes": ["Up", "Down"],
        "description": "Will BTC go up?",
        "event_start_time": event_start_time,
        "end_date": end_date,
    }


def _make_snapshot_dict(asset_id="token-yes"):
    """Build a minimal OrderBookMarketData-compatible dict."""
    return {
        "asset_id": asset_id,
        "timestamp": 1700000000.0,
        "bids": [[0.55, 100.0]],
        "asks": [[0.60, 80.0]],
        "best_bid": 0.55,
        "best_ask": 0.60,
        "mid_price": 0.575,
        "spread": 0.05,
        "bid_volume": 100.0,
        "ask_volume": 80.0,
        "weighted_mid": 0.577,
        "imbalance": 0.111,
    }


def _make_mgr(interval="5m", discover_fn=None):
    """Build a PolymarketFeedManager with an optional mock discovery function."""
    mgr = PolymarketFeedManager(interval)
    if discover_fn is not None:
        mgr._discover_fn = discover_fn
    return mgr


# ---------------------------------------------------------------------------
# Construction and validation
# ---------------------------------------------------------------------------

def test_valid_intervals():
    for interval in ("5m", "15m", "4h"):
        mgr = PolymarketFeedManager(interval)
        assert mgr._interval == interval


def test_invalid_interval_raises():
    with pytest.raises(ValueError, match="Invalid interval"):
        PolymarketFeedManager("1m")
    with pytest.raises(ValueError, match="Invalid interval"):
        PolymarketFeedManager("60m")
    with pytest.raises(ValueError, match="Invalid interval"):
        PolymarketFeedManager("")


def test_name_property():
    assert PolymarketFeedManager("5m").name == "polymarket-btc-5m"
    assert PolymarketFeedManager("15m").name == "polymarket-btc-15m"
    assert PolymarketFeedManager("4h").name == "polymarket-btc-4h"


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------

def test_create_stores_publishers_and_market_data():
    mgr = PolymarketFeedManager("5m")
    pub = MagicMock()
    md = MagicMock()
    mgr.create(feeds=[], publishers=[pub], market_data=md)
    assert mgr._publishers == [pub]
    assert mgr._market_data is md
    assert mgr._created is True


def test_run_before_create_raises():
    mgr = PolymarketFeedManager("5m")
    with pytest.raises(RuntimeError, match="Must call create"):
        mgr.run()


# ---------------------------------------------------------------------------
# _discover_market
# ---------------------------------------------------------------------------

def test_discover_market_returns_on_first_success():
    market = _make_market()
    mock_fn = MagicMock(return_value=market)
    mgr = _make_mgr(discover_fn=mock_fn)

    result = mgr._discover_market()
    assert result == market
    mock_fn.assert_called_once()


def test_discover_market_retries_on_none():
    market = _make_market()
    mock_fn = MagicMock(side_effect=[None, None, market])
    mgr = _make_mgr(discover_fn=mock_fn)
    # Speed up test by mocking the stop_event wait
    mgr._stop_event = MagicMock()
    mgr._stop_event.is_set.return_value = False
    mgr._stop_event.wait.return_value = None

    result = mgr._discover_market()
    assert result == market
    assert mock_fn.call_count == 3


def test_discover_market_returns_none_on_stop():
    mock_fn = MagicMock(return_value=None)
    mgr = _make_mgr(discover_fn=mock_fn)

    def set_stop_on_wait(**kwargs):
        mgr._stop_event.set()
        return True

    mgr._stop_event.wait = set_stop_on_wait

    result = mgr._discover_market()
    assert result is None


def test_discover_market_backoff_increases():
    mock_fn = MagicMock(return_value=None)
    mgr = _make_mgr(discover_fn=mock_fn)

    wait_timeouts = []
    call_count = [0]

    def mock_wait(timeout=None):
        wait_timeouts.append(timeout)
        call_count[0] += 1
        if call_count[0] >= 4:
            mgr._stop_event.set()
        return mgr._stop_event.is_set()

    mgr._stop_event.wait = mock_wait

    mgr._discover_market()

    assert wait_timeouts[0] == _INITIAL_BACKOFF
    assert wait_timeouts[1] == _INITIAL_BACKOFF * 2
    assert wait_timeouts[2] == _INITIAL_BACKOFF * 4
    for t in wait_timeouts:
        assert t <= _MAX_BACKOFF


# ---------------------------------------------------------------------------
# _on_book_update
# ---------------------------------------------------------------------------

def test_on_book_update_records_to_market_data():
    mgr = PolymarketFeedManager("5m")
    mgr._market_data = MagicMock()
    snap_dict = _make_snapshot_dict()

    mgr._on_book_update(snap_dict)

    mgr._market_data.record.assert_called_once()
    recorded = mgr._market_data.record.call_args[0][0]
    assert recorded.asset_id == "token-yes"
    assert recorded.best_bid == 0.55


def test_on_book_update_with_no_market_data():
    mgr = PolymarketFeedManager("5m")
    mgr._market_data = None
    # Should not raise
    mgr._on_book_update(_make_snapshot_dict())


# ---------------------------------------------------------------------------
# _publish
# ---------------------------------------------------------------------------

def test_publish_calls_all_publishers():
    mgr = PolymarketFeedManager("5m")
    pub1 = MagicMock()
    pub2 = MagicMock()
    md = MagicMock()
    md.export.return_value = [_make_snapshot_dict()]
    mgr._publishers = [pub1, pub2]
    mgr._market_data = md

    market = _make_market()
    mgr._publish(market)

    assert pub1.publish_json.call_count == 1
    assert pub2.publish_json.call_count == 1


def test_publish_skips_when_no_snapshots():
    mgr = PolymarketFeedManager("5m")
    pub = MagicMock()
    md = MagicMock()
    md.export.return_value = []
    mgr._publishers = [pub]
    mgr._market_data = md

    mgr._publish(_make_market())
    pub.publish_json.assert_not_called()


def test_publish_payload_structure():
    mgr = PolymarketFeedManager("5m")
    pub = MagicMock()
    md = MagicMock()
    snap = _make_snapshot_dict()
    md.export.return_value = [snap]
    mgr._publishers = [pub]
    mgr._market_data = md

    market = _make_market(slug="btc-updown-5m-123")
    mgr._publish(market)

    key, payload = pub.publish_json.call_args[0]
    assert payload["slug"] == "btc-updown-5m-123"
    assert payload["interval"] == "5m"
    assert payload["market_id"] == "market-1"
    assert payload["snapshot_count"] == 1
    assert payload["snapshots"] == [snap]


def test_publish_handles_publisher_error():
    mgr = PolymarketFeedManager("5m")
    pub1 = MagicMock()
    pub1.publish_json.side_effect = Exception("S3 error")
    pub2 = MagicMock()
    md = MagicMock()
    md.export.return_value = [_make_snapshot_dict()]
    mgr._publishers = [pub1, pub2]
    mgr._market_data = md

    # Should not raise; pub2 still gets called
    mgr._publish(_make_market())
    pub2.publish_json.assert_called_once()


# ---------------------------------------------------------------------------
# _build_s3_key
# ---------------------------------------------------------------------------

def test_s3_key_format():
    mgr = PolymarketFeedManager("5m")
    market = _make_market(
        event_start_time="2023-11-14T22:13:20Z",
        end_date="2023-11-14T22:18:20Z",
    )
    key = mgr._build_s3_key(market)

    start_ts = _parse_iso_to_epoch("2023-11-14T22:13:20Z")
    end_ts = _parse_iso_to_epoch("2023-11-14T22:18:20Z")
    expected = f"polymarket/polymarket-btc-5m/{start_ts:.6f}-{end_ts:.6f}"
    assert key == expected


def test_s3_key_different_intervals():
    for interval in ("5m", "15m", "4h"):
        mgr = PolymarketFeedManager(interval)
        market = _make_market()
        key = mgr._build_s3_key(market)
        assert f"polymarket-btc-{interval}" in key


# ---------------------------------------------------------------------------
# _parse_iso_to_epoch
# ---------------------------------------------------------------------------

def test_parse_iso_to_epoch_with_z():
    result = _parse_iso_to_epoch("2023-11-14T22:13:20Z")
    assert isinstance(result, float)
    assert result > 0


def test_parse_iso_to_epoch_with_offset():
    result = _parse_iso_to_epoch("2023-11-14T22:13:20+00:00")
    assert isinstance(result, float)
    assert result > 0


def test_parse_iso_to_epoch_roundtrip():
    ts_z = _parse_iso_to_epoch("2023-11-14T22:13:20Z")
    ts_offset = _parse_iso_to_epoch("2023-11-14T22:13:20+00:00")
    assert ts_z == ts_offset


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

def test_stop_sets_event():
    mgr = PolymarketFeedManager("5m")
    mgr.stop()
    assert mgr._stop_event.is_set()


def test_stop_stops_current_feed():
    mgr = PolymarketFeedManager("5m")
    feed = MagicMock()
    mgr._current_feed = feed
    mgr.stop()
    feed.stop.assert_called_once()


def test_stop_noop_without_feed():
    mgr = PolymarketFeedManager("5m")
    mgr._current_feed = None
    # Should not raise
    mgr.stop()
    assert mgr._stop_event.is_set()


# ---------------------------------------------------------------------------
# Full run loop (integration-style with mocks)
# ---------------------------------------------------------------------------

@patch("feedManager.impl.PolymarketFeedManager.PolymarketDataFeed")
def test_run_single_market_cycle(MockFeed):
    market = _make_market()

    mock_feed = MagicMock()
    mock_feed._closed_event = threading.Event()
    MockFeed.return_value = mock_feed

    # Simulate market close immediately on start
    def start_side_effect():
        mock_feed._closed_event.set()
    mock_feed.start.side_effect = start_side_effect

    md = MagicMock()
    md.export.return_value = [_make_snapshot_dict()]
    pub = MagicMock()

    mgr = PolymarketFeedManager("5m")

    cycle = [0]
    def discover_cycle():
        cycle[0] += 1
        if cycle[0] == 1:
            return market
        mgr.stop()
        return None
    mgr._discover_fn = discover_cycle

    mgr.create(feeds=[], publishers=[pub], market_data=md)
    mgr.run()

    mock_feed.start.assert_called_once()
    mock_feed.stop.assert_called_once()
    md.export.assert_called_once()
    pub.publish_json.assert_called_once()


@patch("feedManager.impl.PolymarketFeedManager.PolymarketDataFeed")
def test_run_stop_during_collection(MockFeed):
    market = _make_market()

    mock_feed = MagicMock()
    mock_feed._closed_event = threading.Event()
    MockFeed.return_value = mock_feed

    md = MagicMock()
    md.export.return_value = []
    pub = MagicMock()

    mgr = PolymarketFeedManager("5m")
    mgr._discover_fn = MagicMock(return_value=market)

    mgr.create(feeds=[], publishers=[pub], market_data=md)

    # Stop shortly after feed starts
    def start_and_schedule_stop():
        threading.Timer(0.1, mgr.stop).start()
    mock_feed.start.side_effect = start_and_schedule_stop

    mgr.run()

    mock_feed.start.assert_called_once()
    assert mgr._stop_event.is_set()


def test_run_stop_during_discovery():
    mgr = PolymarketFeedManager("5m")
    mgr._discover_fn = MagicMock(return_value=None)
    mgr.create(feeds=[], publishers=[MagicMock()], market_data=MagicMock())

    # Stop shortly after run starts
    threading.Timer(0.1, mgr.stop).start()

    mgr.run()

    assert mgr._stop_event.is_set()


@patch("feedManager.impl.PolymarketFeedManager.PolymarketDataFeed")
def test_run_multiple_cycles(MockFeed):
    market1 = _make_market(slug="btc-updown-5m-100")
    market2 = _make_market(slug="btc-updown-5m-200")

    mock_feed = MagicMock()
    mock_feed._closed_event = threading.Event()
    MockFeed.return_value = mock_feed

    # Close immediately on each start
    def start_side_effect():
        mock_feed._closed_event.set()
    mock_feed.start.side_effect = start_side_effect

    md = MagicMock()
    md.export.return_value = [_make_snapshot_dict()]
    pub = MagicMock()

    mgr = PolymarketFeedManager("5m")

    cycle = [0]
    def discover_cycle():
        cycle[0] += 1
        if cycle[0] == 1:
            return market1
        elif cycle[0] == 2:
            mock_feed._closed_event.clear()
            mock_feed._closed_event.set()
            return market2
        else:
            mgr.stop()
            return None
    mgr._discover_fn = discover_cycle

    mgr.create(feeds=[], publishers=[pub], market_data=md)
    mgr.run()

    assert md.export.call_count == 2
    assert pub.publish_json.call_count == 2


# ---------------------------------------------------------------------------
# _wait_for_close
# ---------------------------------------------------------------------------

def test_wait_for_close_returns_on_closed_event():
    mgr = PolymarketFeedManager("5m")
    feed = MagicMock()
    closed_event = threading.Event()
    feed._closed_event = closed_event

    market = _make_market()

    # Close after a short delay
    threading.Timer(0.05, closed_event.set).start()

    start = time.time()
    mgr._wait_for_close(feed, market)
    elapsed = time.time() - start

    assert elapsed < 2.0  # Should return quickly


def test_wait_for_close_returns_on_stop_event():
    mgr = PolymarketFeedManager("5m")
    feed = MagicMock()
    feed._closed_event = threading.Event()  # Never set

    market = _make_market()

    threading.Timer(0.05, mgr.stop).start()

    start = time.time()
    mgr._wait_for_close(feed, market)
    elapsed = time.time() - start

    assert elapsed < 2.0


def test_wait_for_close_handles_invalid_end_date():
    mgr = PolymarketFeedManager("5m")
    feed = MagicMock()
    closed_event = threading.Event()
    feed._closed_event = closed_event

    market = _make_market(end_date="not-a-date")

    # Close quickly so test doesn't hang
    threading.Timer(0.05, closed_event.set).start()

    mgr._wait_for_close(feed, market)
    # Should not raise
