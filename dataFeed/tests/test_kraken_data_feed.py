import json
import time
from unittest.mock import MagicMock, patch

import pytest

from dataFeed.FeedHealth import FeedHealth, FeedStatus
from dataFeed.impl.KrakenDataFeed import KrakenDataFeed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TRADE = json.dumps({
    "channel": "trade",
    "type": "update",
    "data": [
        {
            "symbol": "BTC/USD",
            "side": "buy",
            "price": "68500.25",
            "qty": "0.001",
            "timestamp": "2023-11-14T22:13:20.123Z",
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
    feed = KrakenDataFeed()
    print(f"  feed.name = {feed.name!r}")
    assert feed.name == "kraken-btc-usd"


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def test_fetch_returns_none_before_any_data():
    feed = KrakenDataFeed()
    result = feed.fetch()
    print(f"  fetch() before data = {result}")
    assert result is None


def test_fetch_returns_latest_tick():
    feed = KrakenDataFeed()
    _simulate_message(feed)
    tick = feed.fetch()
    print(f"  fetch() = {tick}")
    assert tick is not None
    assert tick["price"] == 68500.25
    assert tick["source"] == "kraken"
    assert tick["timestamp"] == pytest.approx(1700000000.123, abs=1.0)


def test_fetch_returns_most_recent_message():
    feed = KrakenDataFeed()
    _simulate_message(feed)
    second = json.dumps({
        "channel": "trade",
        "data": [{"symbol": "BTC/USD", "price": "69000.00", "timestamp": "2023-11-14T22:13:21.000Z"}],
    })
    _simulate_message(feed, second)
    tick = feed.fetch()
    print(f"  first msg price=68500.25, second msg price=69000.00")
    print(f"  fetch() returned price={tick['price']} (should be latest)")
    assert tick["price"] == 69000.00


# ---------------------------------------------------------------------------
# on_tick callback
# ---------------------------------------------------------------------------

def test_on_tick_callback_fires():
    cb = MagicMock()
    feed = KrakenDataFeed(on_tick=cb)
    _simulate_message(feed)
    cb.assert_called_once()
    tick = cb.call_args[0][0]
    print(f"  on_tick called with: {tick}")
    assert tick["price"] == 68500.25


def test_on_tick_not_required():
    feed = KrakenDataFeed()
    _simulate_message(feed)  # should not raise
    print(f"  no callback set — no crash")


# ---------------------------------------------------------------------------
# health — before start (DOWN)
# ---------------------------------------------------------------------------

def test_health_down_before_start():
    feed = KrakenDataFeed()
    h = feed.health()
    print(f"  health = {h.status.value}, last_update={h.last_update}, msg={h.message!r}")
    assert h.status == FeedStatus.DOWN
    assert h.last_update == 0.0


# ---------------------------------------------------------------------------
# health — OK
# ---------------------------------------------------------------------------

def test_health_ok_when_connected_and_fresh():
    feed = KrakenDataFeed()
    feed._connected = True
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
    feed = KrakenDataFeed()
    feed._connected = True
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
    feed = KrakenDataFeed()
    feed._connected = True
    _simulate_message(feed)
    feed._last_message_time = time.time() - 90
    h = feed.health()
    print(f"  health = {h.status.value}, msg={h.message!r}")
    assert h.status == FeedStatus.DOWN
    assert "no data" in h.message


# ---------------------------------------------------------------------------
# health — geo-blocked
# ---------------------------------------------------------------------------

def test_health_down_when_geo_blocked():
    feed = KrakenDataFeed()
    feed._geo_blocked = True
    h = feed.health()
    print(f"  health = {h.status.value}, msg={h.message!r}")
    assert h.status == FeedStatus.DOWN
    assert h.message == "geo-blocked"


# ---------------------------------------------------------------------------
# _on_error
# ---------------------------------------------------------------------------

def test_on_error_increments_count():
    feed = KrakenDataFeed()
    feed._on_error(None, Exception("timeout"))
    print(f"  error_count after 1 error: {feed._error_count}")
    assert feed._error_count == 1


def test_on_error_detects_geo_block():
    feed = KrakenDataFeed()
    feed._on_error(None, Exception("HTTP 451 Unavailable"))
    print(f"  geo_blocked={feed._geo_blocked} (error: 'HTTP 451 Unavailable')")
    assert feed._geo_blocked is True


def test_on_error_detects_forbidden():
    feed = KrakenDataFeed()
    feed._on_error(None, Exception("403 Forbidden"))
    print(f"  geo_blocked={feed._geo_blocked} (error: '403 Forbidden')")
    assert feed._geo_blocked is True


# ---------------------------------------------------------------------------
# _on_close
# ---------------------------------------------------------------------------

def test_on_close_sets_disconnected():
    feed = KrakenDataFeed()
    feed._connected = True
    feed._on_close(None, 1000, "normal")
    print(f"  connected={feed._connected} after close(1000)")
    assert feed._connected is False


def test_on_close_451_sets_geo_blocked():
    feed = KrakenDataFeed()
    feed._on_close(None, 451, "geo-blocked")
    print(f"  geo_blocked={feed._geo_blocked} after close(451)")
    assert feed._geo_blocked is True


# ---------------------------------------------------------------------------
# _on_message — edge cases
# ---------------------------------------------------------------------------

def test_on_message_ignores_bad_json():
    feed = KrakenDataFeed()
    feed._on_message(None, "not json {{{")
    print(f"  fetch after bad json = {feed.fetch()}, msg_count={feed._message_count}")
    assert feed.fetch() is None
    assert feed._message_count == 0


def test_on_message_ignores_non_trade_channel():
    feed = KrakenDataFeed()
    heartbeat = json.dumps({"channel": "heartbeat"})
    feed._on_message(None, heartbeat)
    print(f"  fetch after heartbeat = {feed.fetch()}, msg_count={feed._message_count}")
    assert feed.fetch() is None
    assert feed._message_count == 0


def test_on_message_ignores_zero_price():
    feed = KrakenDataFeed()
    msg = json.dumps({
        "channel": "trade",
        "data": [{"symbol": "BTC/USD", "price": "0", "timestamp": "2023-11-14T22:13:20.123Z"}],
    })
    feed._on_message(None, msg)
    print(f"  fetch after zero-price = {feed.fetch()}, msg_count={feed._message_count}")
    assert feed.fetch() is None
    assert feed._message_count == 0


def test_on_message_falls_back_to_wall_clock_when_no_timestamp():
    feed = KrakenDataFeed()
    msg = json.dumps({
        "channel": "trade",
        "data": [{"symbol": "BTC/USD", "price": "70000.00"}],
    })
    before = time.time()
    feed._on_message(None, msg)
    after = time.time()
    tick = feed.fetch()
    print(f"  tick timestamp={tick['timestamp']}, wall clock range=[{before}, {after}]")
    assert before <= tick["timestamp"] <= after


# ---------------------------------------------------------------------------
# start / stop (mocked — no real WS)
# ---------------------------------------------------------------------------

@patch("dataFeed.impl.KrakenDataFeed.websocket.WebSocketApp")
def test_start_stop_lifecycle(mock_ws_cls):
    mock_app = MagicMock()
    mock_app.run_forever = MagicMock(side_effect=lambda **kw: time.sleep(0.1))
    mock_ws_cls.return_value = mock_app

    feed = KrakenDataFeed()
    feed.start()
    time.sleep(0.3)
    feed.stop()

    print(f"  running={feed._running}, ws created={mock_ws_cls.called}")
    assert not feed._running
    mock_ws_cls.assert_called()


def test_start_is_idempotent():
    feed = KrakenDataFeed()
    with patch.object(feed, "_connect"):
        feed.start()
        thread1 = feed._thread
        feed.start()
        print(f"  same thread after double start: {feed._thread is thread1}")
        assert feed._thread is thread1
        feed._running = False


# ---------------------------------------------------------------------------
# _on_open sends subscription
# ---------------------------------------------------------------------------

def test_on_open_sends_subscribe():
    feed = KrakenDataFeed()
    mock_ws = MagicMock()
    feed._on_open(mock_ws)
    print(f"  connected={feed._connected}")
    assert feed._connected is True
    mock_ws.send.assert_called_once()
    payload = json.loads(mock_ws.send.call_args[0][0])
    print(f"  subscribe payload={payload}")
    assert payload["method"] == "subscribe"
    assert payload["params"]["channel"] == "trade"
    assert "BTC/USD" in payload["params"]["symbol"]
