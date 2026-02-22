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
from blueprints.storage import storage_bp, init_storage
from blueprints.debug import debug_bp, init_debug

app = Flask(__name__)
app.secret_key = os.urandom(24)

APP_PASSWORD = os.environ.get("APP_PASSWORD", "vader")
publisher = S3Publisher(prefix="market-data")

# Feed manager registry: name -> {"manager": FeedManager, "market_data": ..., "running": bool, "thread": ...}
MANAGERS = {}


def _register_polymarket_manager(manager):
    market_data = OrderBookData()
    manager.create(feeds=[], publishers=[publisher], market_data=market_data)
    MANAGERS[manager.name] = {
        "manager": manager,
        "market_data": market_data,
        "running": False,
        "thread": None,
    }


def _register_btc_manager():
    manager = BtcPriceFeedManager()
    market_data = TickMarketData()
    btc_feeds = [
        BinanceDataFeed(),
        KrakenDataFeed(),
        CoinbaseDataFeed(publisher=publisher),
        ChainlinkDataFeed(publisher=publisher),
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
_register_polymarket_manager(PolymarketFeedManager("5m"))
_register_polymarket_manager(PolymarketFeedManager("15m"))
_register_polymarket_manager(PolymarketFeedManager("4h"))


# -- Auth ------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# -- Blueprints ----------------------------------------------------------------

init_storage(publisher, login_required)
init_debug(login_required)
app.register_blueprint(storage_bp)
app.register_blueprint(debug_bp)


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
    if isinstance(entry["manager"], BtcPriceFeedManager):
        return render_template("btc_manager.html", manager_name=name)
    return render_template("manager.html", manager_name=name)


# -- Manager API -----------------------------------------------------------

def _get_manager_health(entry):
    """Extract health from manager, or return stopped."""
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

    if isinstance(manager, BtcPriceFeedManager):
        return _btc_manager_detail(name, entry, health)

    return _polymarket_manager_detail(entry, health)


def _btc_manager_detail(name, entry, health):
    """Build detail response for the BTC feed manager."""
    manager = entry["manager"]
    feeds_data = []
    total_messages = 0
    total_errors = 0

    for feed in manager.feeds:
        last_msg = getattr(feed, "_last_message_time", 0)
        lag = round(time.time() - last_msg, 2) if last_msg > 0 else None
        h = feed.health()

        last_tick = None
        try:
            fetched = feed.fetch()
            if fetched is not None:
                last_tick = fetched
        except Exception:
            pass

        connected = getattr(feed, "_connected", False)
        if hasattr(connected, "is_set"):
            connected = connected.is_set()

        msg_count = getattr(feed, "_message_count", 0)
        err_count = getattr(feed, "_error_count", 0)

        feeds_data.append({
            "name": feed.name,
            "connected": bool(connected),
            "message_count": msg_count,
            "error_count": err_count,
            "lag_seconds": lag,
            "health": {"status": h.status.value, "message": h.message},
            "last_tick": last_tick,
        })

        total_messages += msg_count
        total_errors += err_count

    market_data = entry["market_data"]
    tick_count = len(market_data._ticks) if hasattr(market_data, "_ticks") else 0

    return jsonify({
        "name": name,
        "type": "btc",
        "running": entry["running"],
        "health": health,
        "feeds": feeds_data,
        "total_messages": total_messages,
        "total_errors": total_errors,
        "tick_count": tick_count,
    })


def _polymarket_manager_detail(entry, health):
    """Build detail response for a Polymarket feed manager."""
    manager = entry["manager"]

    result = {
        "name": manager.name,
        "type": "polymarket",
        "running": entry["running"],
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
