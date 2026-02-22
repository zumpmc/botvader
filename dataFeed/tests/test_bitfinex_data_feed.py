import json
import time
from unittest.mock import MagicMock, patch

import pytest

from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.impl.BitfinexDataFeed import BitfinexDataFeed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Subscription confirmation message
SUB_CONFIRM = json.dumps({
    "event": "subscribed",
    "channel": "trades",
    "chanId": 42,
    "symbol": "tBTCUSD",
    "pair": "BTCUSD",
})

# Trade executed message: [chanId, "te", [ID, MTS, AMOUNT, PRICE]]
SAMPLE_TRADE = json.dumps([42, "te", [123456, 1700000000123, 0.001, 68500.25]])


def _simulate_subscribe(feed):
    """Send a subscription confirmation."""
    feed._on_message(None, SUB_CONFIRM)


def _simulate_message(feed, raw=SAMPLE_TRADE):
    """Call the internal _on_message handler directly."""
    feed._on_message(None, raw)


# ---------------------------------------------------------------------------
# name
# ---------------------------------------------------------------------------

def test_name():
    feed = BitfinexDataFeed()
    assert feed.name == "bitfinex-btc-usd"


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def test_fetch_returns_none_before_any_data():
    feed = BitfinexDataFeed()
    assert feed.fetch() is None


def test_fetch_returns_latest_tick():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    _simulate_message(feed)
    tick = feed.fetch()
    assert tick is not None
    assert tick["price"] == 68500.25
    assert tick["source"] == "bitfinex"
    assert tick["timestamp"] == pytest.approx(1700000000.123, abs=0.001)


def test_fetch_returns_most_recent_message():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    _simulate_message(feed)
    second = json.dumps([42, "te", [123457, 1700000001000, -0.02, 69000.00]])
    _simulate_message(feed, second)
    tick = feed.fetch()
    assert tick["price"] == 69000.00


# ---------------------------------------------------------------------------
# side detection
# ---------------------------------------------------------------------------

def test_positive_amount_is_buy():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    trade = json.dumps([42, "te", [1, 1700000000000, 0.5, 68000.0]])
    _simulate_message(feed, trade)
    tick = feed.fetch()
    assert tick["side"] == "buy"


def test_negative_amount_is_sell():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    trade = json.dumps([42, "te", [1, 1700000000000, -0.5, 68000.0]])
    _simulate_message(feed, trade)
    tick = feed.fetch()
    assert tick["side"] == "sell"
    assert tick["size"] == 0.5  # absolute value


# ---------------------------------------------------------------------------
# on_tick callback
# ---------------------------------------------------------------------------

def test_on_tick_callback_fires():
    cb = MagicMock()
    feed = BitfinexDataFeed(on_tick=cb)
    _simulate_subscribe(feed)
    _simulate_message(feed)
    cb.assert_called_once()
    tick = cb.call_args[0][0]
    assert tick["price"] == 68500.25


def test_on_tick_not_required():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    _simulate_message(feed)  # should not raise


# ---------------------------------------------------------------------------
# subscription confirmation
# ---------------------------------------------------------------------------

def test_subscribe_captures_channel_id():
    feed = BitfinexDataFeed()
    assert feed._trade_chan_id is None
    _simulate_subscribe(feed)
    assert feed._trade_chan_id == 42


def test_ignores_different_channel_id():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    wrong_chan = json.dumps([99, "te", [1, 1700000000000, 0.1, 70000.0]])
    _simulate_message(feed, wrong_chan)
    assert feed.fetch() is None
    assert feed._message_count == 0


# ---------------------------------------------------------------------------
# health — before start (DOWN)
# ---------------------------------------------------------------------------

def test_health_down_before_start():
    feed = BitfinexDataFeed()
    h = feed.health()
    assert h.status == FeedStatus.DOWN
    assert h.last_update == 0.0


# ---------------------------------------------------------------------------
# health — OK
# ---------------------------------------------------------------------------

def test_health_ok_when_connected_and_fresh():
    feed = BitfinexDataFeed()
    feed._connected = True
    _simulate_subscribe(feed)
    _simulate_message(feed)
    h = feed.health()
    assert h.status == FeedStatus.OK
    assert "msgs=1" in h.message


# ---------------------------------------------------------------------------
# health — DEGRADED
# ---------------------------------------------------------------------------

def test_health_degraded_when_stale():
    feed = BitfinexDataFeed()
    feed._connected = True
    _simulate_subscribe(feed)
    _simulate_message(feed)
    feed._last_message_time = time.time() - 45
    h = feed.health()
    assert h.status == FeedStatus.DEGRADED
    assert "stale" in h.message


# ---------------------------------------------------------------------------
# health — DOWN (data too old)
# ---------------------------------------------------------------------------

def test_health_down_when_data_too_old():
    feed = BitfinexDataFeed()
    feed._connected = True
    _simulate_subscribe(feed)
    _simulate_message(feed)
    feed._last_message_time = time.time() - 90
    h = feed.health()
    assert h.status == FeedStatus.DOWN
    assert "no data" in h.message


# ---------------------------------------------------------------------------
# health — geo-blocked
# ---------------------------------------------------------------------------

def test_health_down_when_geo_blocked():
    feed = BitfinexDataFeed()
    feed._geo_blocked = True
    h = feed.health()
    assert h.status == FeedStatus.DOWN
    assert h.message == "geo-blocked"


# ---------------------------------------------------------------------------
# _on_error
# ---------------------------------------------------------------------------

def test_on_error_increments_count():
    feed = BitfinexDataFeed()
    feed._on_error(None, Exception("timeout"))
    assert feed._error_count == 1


def test_on_error_detects_geo_block():
    feed = BitfinexDataFeed()
    feed._on_error(None, Exception("HTTP 451 Unavailable"))
    assert feed._geo_blocked is True


# ---------------------------------------------------------------------------
# _on_close
# ---------------------------------------------------------------------------

def test_on_close_sets_disconnected():
    feed = BitfinexDataFeed()
    feed._connected = True
    feed._on_close(None, 1000, "normal")
    assert feed._connected is False


def test_on_close_451_sets_geo_blocked():
    feed = BitfinexDataFeed()
    feed._on_close(None, 451, "geo-blocked")
    assert feed._geo_blocked is True


# ---------------------------------------------------------------------------
# _on_message — ignores non-te/tu messages
# ---------------------------------------------------------------------------

def test_on_message_ignores_snapshot():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    # Snapshots come as [chanId, [[ID,MTS,AMT,PRICE], ...]]
    snapshot = json.dumps([42, [[1, 1700000000000, 0.1, 68000.0]]])
    _simulate_message(feed, snapshot)
    assert feed.fetch() is None
    assert feed._message_count == 0


def test_on_message_handles_tu_messages():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    tu_msg = json.dumps([42, "tu", [123, 1700000000000, 0.1, 68000.0]])
    _simulate_message(feed, tu_msg)
    tick = feed.fetch()
    assert tick is not None
    assert tick["price"] == 68000.0


# ---------------------------------------------------------------------------
# _on_message — malformed JSON
# ---------------------------------------------------------------------------

def test_on_message_ignores_bad_json():
    feed = BitfinexDataFeed()
    feed._on_message(None, "not json {{{")
    assert feed.fetch() is None
    assert feed._message_count == 0


# ---------------------------------------------------------------------------
# _on_message — invalid price
# ---------------------------------------------------------------------------

def test_on_message_skips_zero_price():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    trade = json.dumps([42, "te", [1, 1700000000000, 0.1, 0]])
    _simulate_message(feed, trade)
    assert feed.fetch() is None


# ---------------------------------------------------------------------------
# batching
# ---------------------------------------------------------------------------

def test_buffer_accumulates_ticks():
    feed = BitfinexDataFeed()
    _simulate_subscribe(feed)
    _simulate_message(feed)
    _simulate_message(feed)
    assert len(feed._buffer) == 2


# ---------------------------------------------------------------------------
# flush
# ---------------------------------------------------------------------------

def test_flush_publishes_to_s3():
    pub = MagicMock()
    feed = BitfinexDataFeed(publisher=pub)
    feed._window_start = 1700000000.0
    _simulate_subscribe(feed)
    _simulate_message(feed)
    feed._flush(window_end=1700000300.0)
    pub.publish_json.assert_called_once()
    key = pub.publish_json.call_args[0][0]
    assert key == "bitfinex/bitfinex-btc-usd/1700000000.000000-1700000300.000000"


def test_flush_skips_empty_buffer():
    pub = MagicMock()
    feed = BitfinexDataFeed(publisher=pub)
    feed._window_start = 1700000000.0
    feed._flush(window_end=1700000300.0)
    pub.publish_json.assert_not_called()


# ---------------------------------------------------------------------------
# start / stop (mocked)
# ---------------------------------------------------------------------------

@patch("dataFeed.impl.BitfinexDataFeed.websocket.WebSocketApp")
def test_start_stop_lifecycle(mock_ws_cls):
    mock_app = MagicMock()
    mock_app.run_forever = MagicMock(side_effect=lambda **kw: time.sleep(0.1))
    mock_ws_cls.return_value = mock_app

    feed = BitfinexDataFeed()
    feed.start()
    time.sleep(0.3)
    feed.stop()

    assert not feed._running
    mock_ws_cls.assert_called()


def test_start_is_idempotent():
    feed = BitfinexDataFeed()
    with patch.object(feed, "_connect"):
        feed.start()
        thread1 = feed._ws_thread
        feed.start()
        assert feed._ws_thread is thread1
        feed._running = False
