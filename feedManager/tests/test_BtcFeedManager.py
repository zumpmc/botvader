import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from feedManager.impl.BtcFeedManager import (
    BtcFeedManager,
    _next_window_boundary,
    _WINDOW_SECONDS,
)
from dataFeed.struct.Tick import Tick
from dataFeed.struct.TickMarketData import TickMarketData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick_dict(price=68500.0, source="binance", ts=None):
    return {
        "timestamp": ts or time.time(),
        "price": price,
        "source": source,
        "size": None,
        "side": None,
    }


def _make_mock_feed(name="mock-btc-usd"):
    feed = MagicMock()
    feed.name = name
    feed._on_tick = None
    feed._last_message_time = 0.0
    feed._message_count = 0
    feed._error_count = 0
    feed._connected = False
    feed.health.return_value = MagicMock(
        status=MagicMock(value="down"),
        message="disconnected, errors=0",
    )
    feed.fetch.return_value = None
    return feed


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_name():
    mgr = BtcFeedManager()
    assert mgr.name == "btc-data"


def test_initial_state():
    mgr = BtcFeedManager()
    assert mgr._feeds == []
    assert mgr._publishers == []
    assert mgr._market_data is None
    assert mgr._created is False


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------

def test_create_stores_feeds_publishers_market_data():
    mgr = BtcFeedManager()
    feeds = [_make_mock_feed("f1"), _make_mock_feed("f2")]
    pub = MagicMock()
    md = TickMarketData()
    mgr.create(feeds=feeds, publishers=[pub], market_data=md)
    assert len(mgr._feeds) == 2
    assert mgr._publishers == [pub]
    assert mgr._market_data is md
    assert mgr._created is True


def test_create_copies_lists():
    mgr = BtcFeedManager()
    feeds = [_make_mock_feed()]
    pubs = [MagicMock()]
    mgr.create(feeds=feeds, publishers=pubs, market_data=TickMarketData())
    feeds.append(_make_mock_feed())
    pubs.append(MagicMock())
    assert len(mgr._feeds) == 1
    assert len(mgr._publishers) == 1


# ---------------------------------------------------------------------------
# run() before create()
# ---------------------------------------------------------------------------

def test_run_before_create_raises():
    mgr = BtcFeedManager()
    with pytest.raises(RuntimeError, match="Must call create"):
        mgr.run()


# ---------------------------------------------------------------------------
# _on_tick
# ---------------------------------------------------------------------------

def test_on_tick_records_to_market_data():
    mgr = BtcFeedManager()
    md = TickMarketData()
    mgr._market_data = md

    tick_dict = _make_tick_dict(price=70000.0, source="kraken")
    mgr._on_tick(tick_dict)

    assert len(md._ticks) == 1
    assert md._ticks[0].price == 70000.0
    assert md._ticks[0].source == "kraken"


def test_on_tick_with_no_market_data():
    mgr = BtcFeedManager()
    mgr._market_data = None
    # Should not raise
    mgr._on_tick(_make_tick_dict())


# ---------------------------------------------------------------------------
# _flush
# ---------------------------------------------------------------------------

def test_flush_groups_by_source_and_publishes():
    mgr = BtcFeedManager()
    md = TickMarketData()
    pub = MagicMock()
    mgr._market_data = md
    mgr._publishers = [pub]
    mgr._window_start = 1000.0

    # Record ticks from different sources
    md.record(Tick(timestamp=1001.0, price=68000.0, source="binance"))
    md.record(Tick(timestamp=1002.0, price=68100.0, source="binance"))
    md.record(Tick(timestamp=1003.0, price=68050.0, source="kraken"))

    mgr._flush(window_end=1300.0)

    assert pub.publish_json.call_count == 2

    calls = {c[0][0]: c[0][1] for c in pub.publish_json.call_args_list}

    binance_key = "binance/binance-btc-usd/1000.000000-1300.000000"
    kraken_key = "kraken/kraken-btc-usd/1000.000000-1300.000000"

    assert binance_key in calls
    assert kraken_key in calls
    assert len(calls[binance_key]) == 2
    assert len(calls[kraken_key]) == 1


def test_flush_empty_data_is_noop():
    mgr = BtcFeedManager()
    md = TickMarketData()
    pub = MagicMock()
    mgr._market_data = md
    mgr._publishers = [pub]
    mgr._window_start = 1000.0

    mgr._flush(window_end=1300.0)

    pub.publish_json.assert_not_called()


def test_flush_advances_window_start():
    mgr = BtcFeedManager()
    md = TickMarketData()
    mgr._market_data = md
    mgr._publishers = [MagicMock()]
    mgr._window_start = 1000.0

    md.record(Tick(timestamp=1001.0, price=68000.0, source="binance"))
    mgr._flush(window_end=1300.0)

    assert mgr._window_start == 1300.0


def test_flush_handles_publisher_error():
    mgr = BtcFeedManager()
    md = TickMarketData()
    pub1 = MagicMock()
    pub1.publish_json.side_effect = Exception("S3 error")
    pub2 = MagicMock()
    mgr._market_data = md
    mgr._publishers = [pub1, pub2]
    mgr._window_start = 1000.0

    md.record(Tick(timestamp=1001.0, price=68000.0, source="binance"))
    # Should not raise
    mgr._flush(window_end=1300.0)

    # pub2 still gets called
    assert pub2.publish_json.call_count == 1


def test_flush_with_no_market_data():
    mgr = BtcFeedManager()
    mgr._market_data = None
    # Should not raise
    mgr._flush(window_end=1300.0)


# ---------------------------------------------------------------------------
# _next_window_boundary
# ---------------------------------------------------------------------------

def test_next_window_boundary():
    # Exact boundary should go to next
    result = _next_window_boundary(300.0)
    assert result == 300.0

    # Mid-window
    result = _next_window_boundary(301.0)
    assert result == 600.0

    result = _next_window_boundary(599.9)
    assert result == 600.0


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

def test_stop_sets_event():
    mgr = BtcFeedManager()
    mgr.stop()
    assert mgr._stop_event.is_set()


# ---------------------------------------------------------------------------
# Full run loop (integration-style with mocks)
# ---------------------------------------------------------------------------

def test_run_starts_all_feeds_and_wires_callbacks():
    mgr = BtcFeedManager()
    feeds = [_make_mock_feed("f1"), _make_mock_feed("f2"), _make_mock_feed("f3")]
    pub = MagicMock()
    md = TickMarketData()
    mgr.create(feeds=feeds, publishers=[pub], market_data=md)

    # Stop immediately after run starts
    threading.Timer(0.1, mgr.stop).start()
    mgr.run()

    for feed in feeds:
        feed.start.assert_called_once()
        feed.stop.assert_called_once()


def test_run_flushes_on_stop():
    mgr = BtcFeedManager()
    feed = _make_mock_feed("binance-btc-usd")

    # Simulate the feed firing on_tick when started
    def start_side_effect():
        if feed._on_tick:
            feed._on_tick(_make_tick_dict(source="binance"))

    feed.start.side_effect = start_side_effect

    pub = MagicMock()
    md = TickMarketData()
    mgr.create(feeds=[feed], publishers=[pub], market_data=md)

    # Stop shortly after start
    threading.Timer(0.15, mgr.stop).start()
    mgr.run()

    # Final flush should have published the tick
    assert pub.publish_json.call_count >= 1


def test_run_stop_during_flush_loop():
    mgr = BtcFeedManager()
    feed = _make_mock_feed()
    pub = MagicMock()
    md = TickMarketData()
    mgr.create(feeds=[feed], publishers=[pub], market_data=md)

    threading.Timer(0.1, mgr.stop).start()
    mgr.run()

    assert mgr._stop_event.is_set()
    feed.start.assert_called_once()
    feed.stop.assert_called_once()
