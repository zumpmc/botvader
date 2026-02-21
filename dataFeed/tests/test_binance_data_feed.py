import json
import time
from unittest.mock import MagicMock, patch

import pytest

from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.impl.BinanceDataFeed import BinanceDataFeed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TRADE = json.dumps({
    "e": "trade",
    "E": 1700000000000,
    "s": "BTCUSDT",
    "t": 123456,
    "p": "68500.25",
    "q": "0.001",
    "T": 1700000000123,
})


def _simulate_message(feed, raw=SAMPLE_TRADE):
    """Call the internal _on_message handler directly."""
    feed._on_message(None, raw)


# ---------------------------------------------------------------------------
# name
# ---------------------------------------------------------------------------

def test_name():
    feed = BinanceDataFeed()
    assert feed.name == "binance-btc-usd"


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def test_fetch_returns_none_before_any_data():
    feed = BinanceDataFeed()
    assert feed.fetch() is None


def test_fetch_returns_latest_tick():
    feed = BinanceDataFeed()
    _simulate_message(feed)
    tick = feed.fetch()
    assert tick is not None
    assert tick["price"] == 68500.25
    assert tick["source"] == "binance"
    assert tick["timestamp"] == pytest.approx(1700000000.123, abs=0.001)


def test_fetch_returns_most_recent_message():
    feed = BinanceDataFeed()
    _simulate_message(feed)
    second = json.dumps({"T": 1700000001000, "p": "69000.00"})
    _simulate_message(feed, second)
    tick = feed.fetch()
    assert tick["price"] == 69000.00


# ---------------------------------------------------------------------------
# on_tick callback
# ---------------------------------------------------------------------------

def test_on_tick_callback_fires():
    cb = MagicMock()
    feed = BinanceDataFeed(on_tick=cb)
    _simulate_message(feed)
    cb.assert_called_once()
    tick = cb.call_args[0][0]
    assert tick["price"] == 68500.25


def test_on_tick_not_required():
    feed = BinanceDataFeed()
    _simulate_message(feed)  # should not raise


# ---------------------------------------------------------------------------
# health — before start (DOWN)
# ---------------------------------------------------------------------------

def test_health_down_before_start():
    feed = BinanceDataFeed()
    h = feed.health()
    assert h.status == FeedStatus.DOWN
    assert h.last_update == 0.0


# ---------------------------------------------------------------------------
# health — OK
# ---------------------------------------------------------------------------

def test_health_ok_when_connected_and_fresh():
    feed = BinanceDataFeed()
    feed._connected = True
    _simulate_message(feed)
    h = feed.health()
    assert h.status == FeedStatus.OK
    assert "msgs=1" in h.message
    assert h.last_update > 0


# ---------------------------------------------------------------------------
# health — DEGRADED (stale data 30-60s)
# ---------------------------------------------------------------------------

def test_health_degraded_when_stale():
    feed = BinanceDataFeed()
    feed._connected = True
    _simulate_message(feed)
    feed._last_message_time = time.time() - 45
    h = feed.health()
    assert h.status == FeedStatus.DEGRADED
    assert "stale" in h.message


# ---------------------------------------------------------------------------
# health — DOWN (data older than 60s)
# ---------------------------------------------------------------------------

def test_health_down_when_data_too_old():
    feed = BinanceDataFeed()
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
    feed = BinanceDataFeed()
    feed._geo_blocked = True
    h = feed.health()
    assert h.status == FeedStatus.DOWN
    assert h.message == "geo-blocked"


# ---------------------------------------------------------------------------
# _on_error
# ---------------------------------------------------------------------------

def test_on_error_increments_count():
    feed = BinanceDataFeed()
    feed._on_error(None, Exception("timeout"))
    assert feed._error_count == 1


def test_on_error_detects_geo_block():
    feed = BinanceDataFeed()
    feed._on_error(None, Exception("HTTP 451 Unavailable"))
    assert feed._geo_blocked is True


def test_on_error_detects_forbidden():
    feed = BinanceDataFeed()
    feed._on_error(None, Exception("403 Forbidden"))
    assert feed._geo_blocked is True


# ---------------------------------------------------------------------------
# _on_close
# ---------------------------------------------------------------------------

def test_on_close_sets_disconnected():
    feed = BinanceDataFeed()
    feed._connected = True
    feed._on_close(None, 1000, "normal")
    assert feed._connected is False


def test_on_close_451_sets_geo_blocked():
    feed = BinanceDataFeed()
    feed._on_close(None, 451, "geo-blocked")
    assert feed._geo_blocked is True


# ---------------------------------------------------------------------------
# _on_message — malformed JSON
# ---------------------------------------------------------------------------

def test_on_message_ignores_bad_json():
    feed = BinanceDataFeed()
    feed._on_message(None, "not json {{{")
    assert feed.fetch() is None
    assert feed._message_count == 0


# ---------------------------------------------------------------------------
# start / stop (mocked — no real WS)
# ---------------------------------------------------------------------------

@patch("dataFeed.impl.BinanceDataFeed.websocket.WebSocketApp")
def test_start_stop_lifecycle(mock_ws_cls):
    mock_app = MagicMock()
    mock_app.run_forever = MagicMock(side_effect=lambda: time.sleep(0.1))
    mock_ws_cls.return_value = mock_app

    feed = BinanceDataFeed()
    feed.start()
    time.sleep(0.3)
    feed.stop()

    assert not feed._running
    mock_ws_cls.assert_called()


def test_start_is_idempotent():
    feed = BinanceDataFeed()
    with patch.object(feed, "_connect"):
        feed.start()
        thread1 = feed._thread
        feed.start()
        assert feed._thread is thread1
        feed._running = False
