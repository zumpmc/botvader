import json
import time
from unittest.mock import MagicMock, patch

import pytest

from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.impl.BybitDataFeed import BybitDataFeed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TRADE = json.dumps({
    "topic": "publicTrade.BTCUSDT",
    "type": "snapshot",
    "data": [
        {
            "T": 1700000000123,
            "s": "BTCUSDT",
            "S": "Buy",
            "v": "0.001",
            "p": "68500.25",
            "L": "PlusTick",
            "i": "123456",
            "BT": False,
        }
    ],
})


def _simulate_message(feed, raw=SAMPLE_TRADE):
    """Call the internal _on_message handler directly."""
    feed._on_message(None, raw)


# ---------------------------------------------------------------------------
# name
# ---------------------------------------------------------------------------

def test_name():
    feed = BybitDataFeed()
    assert feed.name == "bybit-btc-usdt"


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def test_fetch_returns_none_before_any_data():
    feed = BybitDataFeed()
    assert feed.fetch() is None


def test_fetch_returns_latest_tick():
    feed = BybitDataFeed()
    _simulate_message(feed)
    tick = feed.fetch()
    assert tick is not None
    assert tick["price"] == 68500.25
    assert tick["source"] == "bybit"
    assert tick["timestamp"] == pytest.approx(1700000000.123, abs=0.001)


def test_fetch_returns_most_recent_message():
    feed = BybitDataFeed()
    _simulate_message(feed)
    second = json.dumps({
        "topic": "publicTrade.BTCUSDT",
        "data": [{"p": "69000.00", "v": "0.01", "S": "Sell", "T": 1700000001000}],
    })
    _simulate_message(feed, second)
    tick = feed.fetch()
    assert tick["price"] == 69000.00


# ---------------------------------------------------------------------------
# on_tick callback
# ---------------------------------------------------------------------------

def test_on_tick_callback_fires():
    cb = MagicMock()
    feed = BybitDataFeed(on_tick=cb)
    _simulate_message(feed)
    cb.assert_called_once()
    tick = cb.call_args[0][0]
    assert tick["price"] == 68500.25


def test_on_tick_not_required():
    feed = BybitDataFeed()
    _simulate_message(feed)  # should not raise


# ---------------------------------------------------------------------------
# health — before start (DOWN)
# ---------------------------------------------------------------------------

def test_health_down_before_start():
    feed = BybitDataFeed()
    h = feed.health()
    assert h.status == FeedStatus.DOWN
    assert h.last_update == 0.0


# ---------------------------------------------------------------------------
# health — OK
# ---------------------------------------------------------------------------

def test_health_ok_when_connected_and_fresh():
    feed = BybitDataFeed()
    feed._connected = True
    _simulate_message(feed)
    h = feed.health()
    assert h.status == FeedStatus.OK
    assert "msgs=1" in h.message


# ---------------------------------------------------------------------------
# health — DEGRADED
# ---------------------------------------------------------------------------

def test_health_degraded_when_stale():
    feed = BybitDataFeed()
    feed._connected = True
    _simulate_message(feed)
    feed._last_message_time = time.time() - 45
    h = feed.health()
    assert h.status == FeedStatus.DEGRADED
    assert "stale" in h.message


# ---------------------------------------------------------------------------
# health — DOWN (data too old)
# ---------------------------------------------------------------------------

def test_health_down_when_data_too_old():
    feed = BybitDataFeed()
    feed._connected = True
    _simulate_message(feed)
    feed._last_message_time = time.time() - 90
    h = feed.health()
    assert h.status == FeedStatus.DOWN
    assert "no data" in h.message


# ---------------------------------------------------------------------------
# health — geo-blocked
# ---------------------------------------------------------------------------

def test_health_down_when_geo_blocked():
    feed = BybitDataFeed()
    feed._geo_blocked = True
    h = feed.health()
    assert h.status == FeedStatus.DOWN
    assert h.message == "geo-blocked"


# ---------------------------------------------------------------------------
# _on_error
# ---------------------------------------------------------------------------

def test_on_error_increments_count():
    feed = BybitDataFeed()
    feed._on_error(None, Exception("timeout"))
    assert feed._error_count == 1


def test_on_error_detects_geo_block():
    feed = BybitDataFeed()
    feed._on_error(None, Exception("HTTP 451 Unavailable"))
    assert feed._geo_blocked is True


# ---------------------------------------------------------------------------
# _on_close
# ---------------------------------------------------------------------------

def test_on_close_sets_disconnected():
    feed = BybitDataFeed()
    feed._connected = True
    feed._on_close(None, 1000, "normal")
    assert feed._connected is False


def test_on_close_451_sets_geo_blocked():
    feed = BybitDataFeed()
    feed._on_close(None, 451, "geo-blocked")
    assert feed._geo_blocked is True


# ---------------------------------------------------------------------------
# _on_message — ignores non-trade topics
# ---------------------------------------------------------------------------

def test_on_message_ignores_non_trade_topic():
    feed = BybitDataFeed()
    msg = json.dumps({"topic": "orderbook.50.BTCUSDT", "data": []})
    feed._on_message(None, msg)
    assert feed.fetch() is None
    assert feed._message_count == 0


# ---------------------------------------------------------------------------
# _on_message — malformed JSON
# ---------------------------------------------------------------------------

def test_on_message_ignores_bad_json():
    feed = BybitDataFeed()
    feed._on_message(None, "not json {{{")
    assert feed.fetch() is None
    assert feed._message_count == 0


# ---------------------------------------------------------------------------
# _on_message — invalid price
# ---------------------------------------------------------------------------

def test_on_message_skips_zero_price():
    feed = BybitDataFeed()
    msg = json.dumps({
        "topic": "publicTrade.BTCUSDT",
        "data": [{"p": "0", "v": "1", "S": "Buy", "T": 1700000000000}],
    })
    feed._on_message(None, msg)
    assert feed.fetch() is None


# ---------------------------------------------------------------------------
# batching
# ---------------------------------------------------------------------------

def test_buffer_accumulates_ticks():
    feed = BybitDataFeed()
    _simulate_message(feed)
    _simulate_message(feed)
    assert len(feed._buffer) == 2


# ---------------------------------------------------------------------------
# flush
# ---------------------------------------------------------------------------

def test_flush_publishes_to_s3():
    pub = MagicMock()
    feed = BybitDataFeed(publisher=pub)
    feed._window_start = 1700000000.0
    _simulate_message(feed)
    feed._flush(window_end=1700000300.0)
    pub.publish_json.assert_called_once()
    key = pub.publish_json.call_args[0][0]
    assert key == "bybit/bybit-btc-usdt/1700000000.000000-1700000300.000000"


def test_flush_skips_empty_buffer():
    pub = MagicMock()
    feed = BybitDataFeed(publisher=pub)
    feed._window_start = 1700000000.0
    feed._flush(window_end=1700000300.0)
    pub.publish_json.assert_not_called()


# ---------------------------------------------------------------------------
# start / stop (mocked)
# ---------------------------------------------------------------------------

@patch("dataFeed.impl.BybitDataFeed.websocket.WebSocketApp")
def test_start_stop_lifecycle(mock_ws_cls):
    mock_app = MagicMock()
    mock_app.run_forever = MagicMock(side_effect=lambda **kw: time.sleep(0.1))
    mock_ws_cls.return_value = mock_app

    feed = BybitDataFeed()
    feed.start()
    time.sleep(0.3)
    feed.stop()

    assert not feed._running
    mock_ws_cls.assert_called()


def test_start_is_idempotent():
    feed = BybitDataFeed()
    with patch.object(feed, "_connect"):
        feed.start()
        thread1 = feed._ws_thread
        feed.start()
        assert feed._ws_thread is thread1
        feed._running = False
