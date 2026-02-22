import time
from unittest.mock import MagicMock, patch

import pytest

from dataFeed.FeedHealth import FeedHealth, FeedStatus
from feedManager.impl.BtcPriceFeedManager import BtcPriceFeedManager, _next_window_boundary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_feed(name: str, health_status: FeedStatus = FeedStatus.OK) -> MagicMock:
    feed = MagicMock()
    feed.name = name
    feed.health.return_value = FeedHealth(
        status=health_status,
        last_update=time.time(),
        message="ok",
    )
    return feed


def _make_mock_market_data(export_data=None):
    md = MagicMock()
    md.export.return_value = export_data if export_data is not None else []
    return md


# ---------------------------------------------------------------------------
# _next_window_boundary
# ---------------------------------------------------------------------------

def test_next_window_boundary_on_exact():
    # 1699999800 is exactly on a 300s boundary (1699999800 / 300 = 5666666)
    assert _next_window_boundary(1699999800.0) == 1699999800.0


def test_next_window_boundary_mid_window():
    # 1699999900 is 100s into a window, next boundary = 1700000100
    assert _next_window_boundary(1699999900.0) == 1700000100.0


def test_next_window_boundary_just_past():
    assert _next_window_boundary(1699999801.0) == 1700000100.0


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def test_create_stores_components():
    mgr = BtcPriceFeedManager()
    feeds = [_make_mock_feed("feed-a"), _make_mock_feed("feed-b")]
    pubs = [MagicMock()]
    md = _make_mock_market_data()

    mgr.create(feeds, pubs, md)

    assert len(mgr.feeds) == 2
    assert mgr._publishers == pubs
    assert mgr._market_data is md


# ---------------------------------------------------------------------------
# run — starts all feeds
# ---------------------------------------------------------------------------

def test_run_starts_all_feeds():
    mgr = BtcPriceFeedManager()
    f1 = _make_mock_feed("feed-1")
    f2 = _make_mock_feed("feed-2")
    md = _make_mock_market_data()

    mgr.create([f1, f2], [MagicMock()], md)
    mgr.run()
    time.sleep(0.1)

    f1.start.assert_called_once()
    f2.start.assert_called_once()

    mgr.stop()


def test_run_is_idempotent():
    mgr = BtcPriceFeedManager()
    mgr.create([_make_mock_feed("f")], [MagicMock()], _make_mock_market_data())
    mgr.run()
    mgr.run()  # second call should be no-op
    time.sleep(0.1)
    mgr.stop()


# ---------------------------------------------------------------------------
# stop — stops all feeds
# ---------------------------------------------------------------------------

def test_stop_stops_all_feeds():
    mgr = BtcPriceFeedManager()
    f1 = _make_mock_feed("feed-1")
    f2 = _make_mock_feed("feed-2")
    md = _make_mock_market_data()

    mgr.create([f1, f2], [MagicMock()], md)
    mgr.run()
    time.sleep(0.1)
    mgr.stop()

    f1.stop.assert_called_once()
    f2.stop.assert_called_once()


# ---------------------------------------------------------------------------
# health — aggregates all feed health
# ---------------------------------------------------------------------------

def test_health_returns_all_feeds():
    mgr = BtcPriceFeedManager()
    f1 = _make_mock_feed("binance-btc-usd", FeedStatus.OK)
    f2 = _make_mock_feed("kraken-btc-usd", FeedStatus.DEGRADED)
    f3 = _make_mock_feed("okx-btc-usdt", FeedStatus.DOWN)

    mgr.create([f1, f2, f3], [], _make_mock_market_data())

    result = mgr.health()
    assert len(result) == 3
    assert result["binance-btc-usd"].status == FeedStatus.OK
    assert result["kraken-btc-usd"].status == FeedStatus.DEGRADED
    assert result["okx-btc-usdt"].status == FeedStatus.DOWN


# ---------------------------------------------------------------------------
# flush — publishes to all publishers
# ---------------------------------------------------------------------------

def test_flush_publishes_to_all_publishers():
    mgr = BtcPriceFeedManager()
    pub1 = MagicMock()
    pub2 = MagicMock()
    ticks = [{"timestamp": 1700000000.0, "price": 68500.0, "source": "binance"}]
    md = _make_mock_market_data(export_data=ticks)

    mgr.create([], [pub1, pub2], md)
    mgr._window_start = 1700000000.0
    mgr._flush(window_end=1700000300.0)

    pub1.publish_json.assert_called_once()
    pub2.publish_json.assert_called_once()

    key = pub1.publish_json.call_args[0][0]
    assert key == "btc-prices/all/1700000000.000000-1700000300.000000"


def test_flush_skips_empty_export():
    mgr = BtcPriceFeedManager()
    pub = MagicMock()
    md = _make_mock_market_data(export_data=[])

    mgr.create([], [pub], md)
    mgr._window_start = 1700000000.0
    mgr._flush(window_end=1700000300.0)

    pub.publish_json.assert_not_called()


def test_flush_without_market_data():
    mgr = BtcPriceFeedManager()
    pub = MagicMock()
    mgr.create([], [pub], _make_mock_market_data())
    mgr._market_data = None
    mgr._flush(window_end=1700000300.0)
    pub.publish_json.assert_not_called()


# ---------------------------------------------------------------------------
# feeds property
# ---------------------------------------------------------------------------

def test_feeds_returns_copy():
    mgr = BtcPriceFeedManager()
    f1 = _make_mock_feed("f")
    mgr.create([f1], [], _make_mock_market_data())
    feeds = mgr.feeds
    feeds.append(_make_mock_feed("extra"))
    assert len(mgr.feeds) == 1  # original unchanged
