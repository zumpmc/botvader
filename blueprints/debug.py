import collections
import logging
import threading
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

debug_bp = Blueprint("debug", __name__)

_login_required = None

# Ring buffer for log lines
_LOG_BUFFER_SIZE = 500
_log_buffer = collections.deque(maxlen=_LOG_BUFFER_SIZE)
_log_lock = threading.Lock()


class BufferHandler(logging.Handler):
    """Logging handler that writes to an in-memory ring buffer."""

    def emit(self, record):
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
            line = f"{ts} [{record.levelname}] {record.name}: {record.getMessage()}"
            if record.exc_text:
                line += "\n" + record.exc_text
            with _log_lock:
                _log_buffer.append(line)
        except Exception:
            pass


def init_debug(login_required):
    global _login_required
    _login_required = login_required

    # Attach handler to root logger so we capture everything
    handler = BufferHandler()
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)


@debug_bp.route("/debug")
def debug_page():
    return _login_required(lambda: render_template("debug.html"))()


@debug_bp.route("/api/debug/logs")
def api_debug_logs():
    def _handler():
        lines = int(request.args.get("lines", 100))
        with _log_lock:
            recent = list(_log_buffer)[-lines:]
        return jsonify({"lines": recent})

    return _login_required(_handler)()
