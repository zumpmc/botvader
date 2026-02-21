import os
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

from dataFeed.impl.BinanceDataFeed import BinanceDataFeed
from dataFeed.impl.CoinbaseDataFeed import CoinbaseDataFeed
from dataFeed.impl.KrakenDataFeed import KrakenDataFeed
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
