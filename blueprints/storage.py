import json

from flask import Blueprint, jsonify, render_template, request

storage_bp = Blueprint("storage", __name__)

# Set by run.py at registration time
_publisher = None
_login_required = None


def init_storage(publisher, login_required):
    global _publisher, _login_required
    _publisher = publisher
    _login_required = login_required


@storage_bp.route("/storage")
def storage_page():
    return _login_required(lambda: render_template("storage.html"))()


@storage_bp.route("/api/storage")
def api_storage_list():
    def _handler():
        prefix = request.args.get("prefix", "")
        all_keys = _publisher.list_keys(prefix=prefix)

        folders = set()
        objects = []

        for key in all_keys:
            # Strip the publisher's own prefix to get relative path
            relative = key
            if _publisher._prefix:
                relative = key[len(_publisher._prefix) + 1:]

            # Get the part after our current prefix
            if prefix and relative.startswith(prefix):
                remainder = relative[len(prefix):]
            elif not prefix:
                remainder = relative
            else:
                continue

            # Remove leading slash
            if remainder.startswith("/"):
                remainder = remainder[1:]

            if "/" in remainder:
                folder = remainder.split("/")[0] + "/"
                folders.add(folder)
            else:
                objects.append({"key": relative, "full_key": key})

        return jsonify({
            "prefix": prefix,
            "folders": sorted(folders),
            "objects": sorted(objects, key=lambda o: o["key"]),
        })

    return _login_required(_handler)()


@storage_bp.route("/api/storage/object")
def api_storage_object():
    def _handler():
        key = request.args.get("key", "")
        if not key:
            return jsonify({"error": "no key provided"}), 400
        try:
            # key comes from list_keys() which returns full S3 keys
            # (e.g. "market-data/coinbase/..."). Strip the publisher
            # prefix so publisher.get() doesn't double-prepend it.
            relative_key = key
            if _publisher._prefix and key.startswith(_publisher._prefix + "/"):
                relative_key = key[len(_publisher._prefix) + 1:]
            raw = _publisher.get(relative_key)
            data = json.loads(raw)
            return jsonify({"key": key, "data": data})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return _login_required(_handler)()
