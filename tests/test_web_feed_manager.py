"""Tests for FeedManager web routes and API endpoints."""

import os
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")

import time
from unittest.mock import MagicMock, patch
import threading

import pytest

from run import app, MANAGERS
from feedManager.impl.BtcFeedManager import BtcFeedManager


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["authed"] = True
        yield c


@pytest.fixture(autouse=True)
def reset_managers():
    """Reset manager state between tests."""
    for entry in MANAGERS.values():
        entry["running"] = False
        entry["thread"] = None
        mgr = entry["manager"]
        if isinstance(mgr, BtcFeedManager):
            mgr._stop_event.clear()
        else:
            with mgr._lock:
                mgr._current_feed = None
            mgr._stop_event.clear()
    yield
    # Ensure nothing is left running
    for entry in MANAGERS.values():
        if entry["running"]:
            entry["manager"].stop()
            entry["running"] = False


# -- Page routes -----------------------------------------------------------


class TestManagerDetailPage:
    def test_requires_login(self):
        app.config["TESTING"] = True
        with app.test_client() as c:
            res = c.get("/manager/polymarket-btc-5m")
            assert res.status_code == 302
            assert "/login" in res.headers["Location"]

    def test_renders_polymarket_manager(self, client):
        res = client.get("/manager/polymarket-btc-5m")
        assert res.status_code == 200
        assert b"polymarket-btc-5m" in res.data

    def test_renders_btc_manager(self, client):
        res = client.get("/manager/btc-data")
        assert res.status_code == 200
        assert b"btc-data" in res.data

    def test_unknown_manager_redirects(self, client):
        res = client.get("/manager/nonexistent")
        assert res.status_code == 302
        assert "/" in res.headers["Location"]


# -- List API --------------------------------------------------------------


class TestApiManagersList:
    def test_returns_all_managers(self, client):
        res = client.get("/api/managers")
        assert res.status_code == 200
        data = res.get_json()
        names = [m["name"] for m in data]
        assert "btc-data" in names
        assert "polymarket-btc-5m" in names
        assert "polymarket-btc-15m" in names
        assert "polymarket-btc-4h" in names

    def test_stopped_managers_have_stopped_status(self, client):
        res = client.get("/api/managers")
        data = res.get_json()
        for m in data:
            assert m["running"] is False
            assert m["health"]["status"] == "stopped"


# -- BTC Manager Detail API ------------------------------------------------


class TestApiBtcManagerDetail:
    def test_stopped_btc_manager(self, client):
        res = client.get("/api/managers/btc-data")
        assert res.status_code == 200
        data = res.get_json()
        assert data["name"] == "btc-data"
        assert data["type"] == "btc"
        assert data["running"] is False
        assert data["health"]["status"] == "stopped"
        assert "feeds" in data
        assert isinstance(data["feeds"], list)
        assert len(data["feeds"]) == 4
        assert data["total_messages"] == 0
        assert data["total_errors"] == 0
        assert data["tick_count"] == 0

    def test_btc_feeds_have_expected_names(self, client):
        res = client.get("/api/managers/btc-data")
        data = res.get_json()
        feed_names = [f["name"] for f in data["feeds"]]
        assert "binance-btc-usd" in feed_names
        assert "kraken-btc-usd" in feed_names
        assert "coinbase-btc-usd" in feed_names
        assert "chainlink-btc-usd" in feed_names

    def test_btc_feed_fields(self, client):
        res = client.get("/api/managers/btc-data")
        data = res.get_json()
        for feed in data["feeds"]:
            assert "name" in feed
            assert "connected" in feed
            assert "message_count" in feed
            assert "error_count" in feed
            assert "lag_seconds" in feed
            assert "health" in feed
            assert "last_tick" in feed


# -- Polymarket Manager Detail API -----------------------------------------


class TestApiPolymarketManagerDetail:
    def test_unknown_manager_returns_404(self, client):
        res = client.get("/api/managers/nonexistent")
        assert res.status_code == 404
        data = res.get_json()
        assert "error" in data

    def test_stopped_manager(self, client):
        res = client.get("/api/managers/polymarket-btc-5m")
        assert res.status_code == 200
        data = res.get_json()
        assert data["name"] == "polymarket-btc-5m"
        assert data["type"] == "polymarket"
        assert data["running"] is False
        assert data["interval"] == "5m"
        assert data["lag_seconds"] is None
        assert data["message_count"] == 0
        assert data["error_count"] == 0
        assert data["connected"] is False
        assert data["last_data"] is None
        assert data["snapshot_count"] == 0
        assert data["health"]["status"] == "stopped"

    def test_with_active_feed(self, client):
        """Simulate an active feed by injecting a mock _current_feed."""
        entry = MANAGERS["polymarket-btc-5m"]
        entry["running"] = True

        mock_feed = MagicMock()
        mock_feed._last_message_time = time.time() - 2.0
        mock_feed._message_count = 42
        mock_feed._error_count = 1
        mock_feed._connected = threading.Event()
        mock_feed._connected.set()
        mock_feed.health.return_value = MagicMock(
            status=MagicMock(value="ok"),
            message="msgs=42, errors=1",
            last_update=mock_feed._last_message_time,
        )
        mock_feed.fetch.return_value = MagicMock(
            to_dict=MagicMock(return_value={
                "asset_id": "test-asset",
                "timestamp": time.time(),
                "best_bid": 0.52,
                "best_ask": 0.54,
                "mid_price": 0.53,
                "spread": 0.02,
                "bid_volume": 100.0,
                "ask_volume": 80.0,
                "weighted_mid": 0.531,
                "imbalance": 0.11,
                "bids": [[0.52, 50], [0.51, 50]],
                "asks": [[0.54, 40], [0.55, 40]],
            })
        )

        mgr = entry["manager"]
        with mgr._lock:
            mgr._current_feed = mock_feed

        res = client.get("/api/managers/polymarket-btc-5m")
        data = res.get_json()

        assert data["running"] is True
        assert data["message_count"] == 42
        assert data["error_count"] == 1
        assert data["connected"] is True
        assert data["lag_seconds"] is not None
        assert data["lag_seconds"] >= 1.0
        assert data["health"]["status"] == "ok"
        assert data["last_data"] is not None
        assert data["last_data"]["best_bid"] == 0.52

    def test_with_feed_no_data_yet(self, client):
        """Feed is active but hasn't received data yet."""
        entry = MANAGERS["polymarket-btc-15m"]
        entry["running"] = True

        mock_feed = MagicMock()
        mock_feed._last_message_time = 0.0
        mock_feed._message_count = 0
        mock_feed._error_count = 0
        mock_feed._connected = threading.Event()
        mock_feed.health.return_value = MagicMock(
            status=MagicMock(value="down"),
            message="disconnected, errors=0",
            last_update=0.0,
        )
        mock_feed.fetch.return_value = None

        mgr = entry["manager"]
        with mgr._lock:
            mgr._current_feed = mock_feed

        res = client.get("/api/managers/polymarket-btc-15m")
        data = res.get_json()

        assert data["lag_seconds"] is None
        assert data["message_count"] == 0
        assert data["connected"] is False
        assert data["last_data"] is None

    def test_snapshot_count_reflects_market_data(self, client):
        """Verify snapshot_count reads from market_data._snapshots."""
        entry = MANAGERS["polymarket-btc-5m"]
        mock_snapshot = MagicMock()
        entry["market_data"]._snapshots = [mock_snapshot, mock_snapshot, mock_snapshot]

        res = client.get("/api/managers/polymarket-btc-5m")
        data = res.get_json()
        assert data["snapshot_count"] == 3

        entry["market_data"]._snapshots = []


# -- Start/Stop API --------------------------------------------------------


class TestApiManagerStartStop:
    def test_start_unknown_manager(self, client):
        res = client.post("/api/managers/nonexistent/start")
        assert res.status_code == 404

    def test_stop_unknown_manager(self, client):
        res = client.post("/api/managers/nonexistent/stop")
        assert res.status_code == 404

    def test_start_sets_running(self, client):
        entry = MANAGERS["polymarket-btc-5m"]

        # Patch run() to avoid actually connecting to Polymarket
        with patch.object(entry["manager"], "run", side_effect=lambda: time.sleep(0.1)):
            res = client.post("/api/managers/polymarket-btc-5m/start")
            assert res.status_code == 200
            assert res.get_json()["ok"] is True
            assert entry["running"] is True
            assert entry["thread"] is not None

            # Wait for the thread to finish
            entry["thread"].join(timeout=2)

    def test_start_btc_manager_sets_running(self, client):
        entry = MANAGERS["btc-data"]

        with patch.object(entry["manager"], "run", side_effect=lambda: time.sleep(0.1)):
            res = client.post("/api/managers/btc-data/start")
            assert res.status_code == 200
            assert res.get_json()["ok"] is True
            assert entry["running"] is True
            assert entry["thread"] is not None

            entry["thread"].join(timeout=2)

    def test_stop_sets_not_running(self, client):
        entry = MANAGERS["polymarket-btc-5m"]
        entry["running"] = True

        with patch.object(entry["manager"], "stop"):
            res = client.post("/api/managers/polymarket-btc-5m/stop")
            assert res.status_code == 200
            assert res.get_json()["ok"] is True
            assert entry["running"] is False

    def test_stop_btc_manager(self, client):
        entry = MANAGERS["btc-data"]
        entry["running"] = True

        with patch.object(entry["manager"], "stop"):
            res = client.post("/api/managers/btc-data/stop")
            assert res.status_code == 200
            assert res.get_json()["ok"] is True
            assert entry["running"] is False

    def test_start_already_running_is_noop(self, client):
        entry = MANAGERS["polymarket-btc-5m"]
        entry["running"] = True
        existing_thread = MagicMock()
        entry["thread"] = existing_thread

        res = client.post("/api/managers/polymarket-btc-5m/start")
        assert res.status_code == 200
        # Thread should not have changed
        assert entry["thread"] is existing_thread

    def test_stop_already_stopped_is_noop(self, client):
        entry = MANAGERS["polymarket-btc-5m"]
        entry["running"] = False

        res = client.post("/api/managers/polymarket-btc-5m/stop")
        assert res.status_code == 200
        assert entry["running"] is False


# -- API auth --------------------------------------------------------------


class TestApiManagerAuth:
    def test_managers_list_requires_login(self):
        app.config["TESTING"] = True
        with app.test_client() as c:
            res = c.get("/api/managers")
            assert res.status_code == 302

    def test_manager_detail_requires_login(self):
        app.config["TESTING"] = True
        with app.test_client() as c:
            res = c.get("/api/managers/polymarket-btc-5m")
            assert res.status_code == 302

    def test_manager_start_requires_login(self):
        app.config["TESTING"] = True
        with app.test_client() as c:
            res = c.post("/api/managers/polymarket-btc-5m/start")
            assert res.status_code == 302

    def test_manager_stop_requires_login(self):
        app.config["TESTING"] = True
        with app.test_client() as c:
            res = c.post("/api/managers/polymarket-btc-5m/stop")
            assert res.status_code == 302
