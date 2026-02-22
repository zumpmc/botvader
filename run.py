import os
import threading
import time
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

from dataFeed.FeedHealth import FeedStatus
from dataFeed.impl.BinanceDataFeed import BinanceDataFeed
from dataFeed.impl.BitfinexDataFeed import BitfinexDataFeed
from dataFeed.impl.BybitDataFeed import BybitDataFeed
from dataFeed.impl.ChainlinkDataFeed import ChainlinkDataFeed
from dataFeed.impl.CoinbaseDataFeed import CoinbaseDataFeed
from dataFeed.impl.GeminiDataFeed import GeminiDataFeed
from dataFeed.impl.KrakenDataFeed import KrakenDataFeed
from dataFeed.impl.OKXDataFeed import OKXDataFeed
from dataFeed.struct.OrderBookData import OrderBookData
from dataFeed.struct.TickMarketData import TickMarketData
from feedManager import PolymarketFeedManager
from feedManager.impl import BtcPriceFeedManager
from publisher import S3Publisher

app = Flask(__name__)
app.secret_key = os.urandom(24)

APP_PASSWORD = os.environ.get("APP_PASSWORD", "vader")
publisher = S3Publisher(prefix="market-data")

# Feed registry: name -> {"feed": DataFeed, "running": bool}
FEEDS = {}


def _register(feed):
    FEEDS[feed.name] = {"feed": feed, "running": False}


_register(CoinbaseDataFeed(publisher=publisher))
_register(BinanceDataFeed())
_register(KrakenDataFeed())
_register(ChainlinkDataFeed(publisher=publisher))
_register(BitfinexDataFeed(publisher=publisher))
_register(BybitDataFeed(publisher=publisher))
_register(GeminiDataFeed(publisher=publisher))
_register(OKXDataFeed(publisher=publisher))

# Feed manager registry: name -> {"manager": FeedManager, "market_data": ..., "running": bool, "thread": ...}
MANAGERS = {}


def _register_manager(manager):
    market_data = OrderBookData()
    manager.create(feeds=[], publishers=[publisher], market_data=market_data)
    MANAGERS[manager.name] = {
        "manager": manager,
        "market_data": market_data,
        "running": False,
        "thread": None,
    }


_register_manager(PolymarketFeedManager("5m"))
_register_manager(PolymarketFeedManager("15m"))
_register_manager(PolymarketFeedManager("4h"))


def _register_btc_manager():
    manager = BtcPriceFeedManager()
    market_data = TickMarketData()
    btc_feeds = [
        BitfinexDataFeed(publisher=publisher),
        BybitDataFeed(publisher=publisher),
        GeminiDataFeed(publisher=publisher),
        OKXDataFeed(publisher=publisher),
    ]
    manager.create(feeds=btc_feeds, publishers=[publisher], market_data=market_data)
    MANAGERS["btc-price-feeds"] = {
        "manager": manager,
        "market_data": market_data,
        "running": False,
        "thread": None,
    }


_register_btc_manager()


# -- Auth ------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authed"] = True
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Wrong password"), 401
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -- Dashboard -------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    return render_template("index.html")


@app.route("/manager/<name>")
@login_required
def manager_detail(name):
    entry = MANAGERS.get(name)
    if not entry:
        return redirect(url_for("dashboard"))
    return render_template("manager.html", manager_name=name)


# -- API -------------------------------------------------------------------

@app.route("/api/feeds")
@login_required
def api_feeds():
    result = []
    for name, entry in FEEDS.items():
        feed = entry["feed"]
        running = entry["running"]
        if running:
            h = feed.health()
            health = {"status": h.status.value, "message": h.message}
        else:
            health = {"status": "stopped", "message": ""}
        result.append({"name": name, "running": running, "health": health})
    return jsonify(result)


@app.route("/api/feeds/<name>/start", methods=["POST"])
@login_required
def api_start(name):
    entry = FEEDS.get(name)
    if not entry:
        return jsonify({"error": "unknown feed"}), 404
    if not entry["running"]:
        entry["feed"].start()
        entry["running"] = True
    return jsonify({"ok": True})


@app.route("/api/feeds/<name>/stop", methods=["POST"])
@login_required
def api_stop(name):
    entry = FEEDS.get(name)
    if not entry:
        return jsonify({"error": "unknown feed"}), 404
    if entry["running"]:
        entry["feed"].stop()
        entry["running"] = False
    return jsonify({"ok": True})


# -- Manager API -----------------------------------------------------------

def _get_manager_health(entry):
    """Extract health from manager's current feed, or return stopped."""
    manager = entry["manager"]
    if not entry["running"]:
        return {"status": "stopped", "message": "", "last_update": 0}

    # BtcPriceFeedManager exposes a health() dict keyed by feed name
    if isinstance(manager, BtcPriceFeedManager):
        healths = manager.health()
        if not healths:
            return {"status": "ok", "message": "starting feeds...", "last_update": 0}
        # Aggregate: worst status wins
        worst = FeedStatus.OK
        msgs = []
        last_update = 0
        for name, h in healths.items():
            if h.status.value == "down":
                worst = FeedStatus.DOWN
            elif h.status.value == "degraded" and worst != FeedStatus.DOWN:
                worst = FeedStatus.DEGRADED
            if h.message:
                msgs.append(f"{name}: {h.message}")
            if h.last_update > last_update:
                last_update = h.last_update
        msg = "; ".join(msgs) if msgs else f"{len(healths)} feeds active"
        return {"status": worst.value, "message": msg, "last_update": last_update}

    # PolymarketFeedManager path
    with manager._lock:
        feed = manager._current_feed
    if feed is None:
        return {"status": "ok", "message": "discovering market...", "last_update": 0}
    h = feed.health()
    return {"status": h.status.value, "message": h.message, "last_update": h.last_update}


@app.route("/api/managers")
@login_required
def api_managers():
    result = []
    for name, entry in MANAGERS.items():
        health = _get_manager_health(entry)
        result.append({"name": name, "running": entry["running"], "health": health})
    return jsonify(result)


@app.route("/api/managers/<name>")
@login_required
def api_manager_detail(name):
    entry = MANAGERS.get(name)
    if not entry:
        return jsonify({"error": "unknown manager"}), 404

    manager = entry["manager"]
    health = _get_manager_health(entry)

    # BtcPriceFeedManager: aggregate metrics across all feeds
    if isinstance(manager, BtcPriceFeedManager):
        total_messages = 0
        total_errors = 0
        connected_count = 0
        min_lag = None
        feeds_detail = []

        for feed in manager.feeds:
            msg_count = getattr(feed, "_message_count", 0)
            err_count = getattr(feed, "_error_count", 0)
            total_messages += msg_count
            total_errors += err_count
            is_connected = getattr(feed, "_connected", False)
            if is_connected:
                connected_count += 1
            last_msg = getattr(feed, "_last_message_time", 0)
            lag = round(time.time() - last_msg, 2) if last_msg > 0 else None
            if lag is not None and (min_lag is None or lag < min_lag):
                min_lag = lag
            feeds_detail.append({
                "name": feed.name,
                "connected": is_connected,
                "message_count": msg_count,
                "error_count": err_count,
                "lag_seconds": lag,
            })

        market_data = entry["market_data"]
        tick_count = len(market_data._ticks) if hasattr(market_data, "_ticks") else 0

        result = {
            "name": name,
            "running": entry["running"],
            "type": "btc-price",
            "health": health,
            "connected": connected_count > 0,
            "connected_count": connected_count,
            "total_feeds": len(manager.feeds),
            "lag_seconds": min_lag,
            "message_count": total_messages,
            "error_count": total_errors,
            "snapshot_count": tick_count,
            "feeds": feeds_detail,
            "last_data": None,
        }
        return jsonify(result)

    # PolymarketFeedManager path
    result = {
        "name": name,
        "running": entry["running"],
        "type": "polymarket",
        "interval": manager._interval,
        "health": health,
        "connected": False,
        "lag_seconds": None,
        "message_count": 0,
        "error_count": 0,
        "snapshot_count": len(entry["market_data"]._snapshots),
        "last_data": None,
    }

    with manager._lock:
        feed = manager._current_feed

    if feed is not None:
        last_msg = feed._last_message_time
        if last_msg > 0:
            result["lag_seconds"] = round(time.time() - last_msg, 2)
        result["message_count"] = feed._message_count
        result["error_count"] = feed._error_count
        result["connected"] = feed._connected.is_set()

        try:
            fetched = feed.fetch()
            if fetched is not None:
                result["last_data"] = fetched.to_dict() if hasattr(fetched, "to_dict") else fetched
        except Exception:
            pass

    return jsonify(result)


def _run_manager(entry):
    try:
        entry["manager"].run()
    finally:
        entry["running"] = False
        entry["thread"] = None


@app.route("/api/managers/<name>/start", methods=["POST"])
@login_required
def api_manager_start(name):
    entry = MANAGERS.get(name)
    if not entry:
        return jsonify({"error": "unknown manager"}), 404
    if not entry["running"]:
        thread = threading.Thread(target=_run_manager, args=(entry,), daemon=True)
        entry["thread"] = thread
        entry["running"] = True
        thread.start()
    return jsonify({"ok": True})


@app.route("/api/managers/<name>/stop", methods=["POST"])
@login_required
def api_manager_stop(name):
    entry = MANAGERS.get(name)
    if not entry:
        return jsonify({"error": "unknown manager"}), 404
    if entry["running"]:
        entry["manager"].stop()
        entry["running"] = False
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
