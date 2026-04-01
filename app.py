import os
import sys
import socket
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

import paths
import database
import email_parser as ep


# ── Path setup ────────────────────────────────────────────────────────────────

_RESOURCE_DIR = paths.get_resource_dir()
_DATA_DIR = paths.get_data_dir()
CONFIG_PATH = os.path.join(_DATA_DIR, "config.json")

# On first run copy the example config so the user has something to edit
if not os.path.exists(CONFIG_PATH):
    import shutil
    example = os.path.join(_RESOURCE_DIR, "config.example.json")
    if os.path.exists(example):
        shutil.copy(example, CONFIG_PATH)


# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder=os.path.join(_RESOURCE_DIR, "templates"),
    static_folder=os.path.join(_RESOURCE_DIR, "static"),
)
CORS(app)

scheduler = BackgroundScheduler(daemon=True)
email_status = {
    "last_check": None,
    "status": "idle",
    "message": "Not checked yet",
    "found": 0,
}
_check_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _wait_for_flask(port: int, timeout: float = 10.0) -> bool:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def load_config():
    import json
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg):
    import json
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Background jobs ───────────────────────────────────────────────────────────

def run_email_check():
    global email_status
    if not _check_lock.acquire(blocking=False):
        return
    try:
        email_status["status"] = "running"
        email_status["message"] = "Checking emails..."
        cfg = load_config()
        checker = ep.EmailChecker(cfg)
        count = checker.check_and_process()
        email_status["last_check"] = _now()
        email_status["status"] = "idle"
        email_status["found"] = count
        email_status["message"] = f"Done — {count} new/updated order(s)"
    except Exception as e:
        email_status["status"] = "error"
        email_status["message"] = str(e)
        email_status["last_check"] = _now()
    finally:
        _check_lock.release()


def reschedule_checker(cfg):
    interval = cfg.get("imap", {}).get("check_interval_seconds", 300)
    if scheduler.get_job("email_check"):
        scheduler.remove_job("email_check")
    scheduler.add_job(
        run_email_check, "interval", seconds=interval,
        id="email_check", misfire_grace_time=60,
    )


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Orders API ────────────────────────────────────────────────────────────────

@app.route("/api/orders", methods=["GET"])
def api_get_orders():
    orders = database.get_orders(
        status=request.args.get("status"),
        merchant=request.args.get("merchant"),
        search=request.args.get("search"),
    )
    return jsonify(orders)


@app.route("/api/orders", methods=["POST"])
def api_add_order():
    data = request.json or {}
    if not data.get("email_uid"):
        data["email_uid"] = f"manual:{_now()}"
    if not data.get("order_date"):
        data["order_date"] = _today()
    database.upsert_order_by_uid(data)
    return jsonify({"success": True}), 201


@app.route("/api/orders/<int:order_id>", methods=["PUT"])
def api_update_order(order_id):
    ok = database.update_order(order_id, request.json or {})
    return jsonify({"success": ok})


@app.route("/api/orders/<int:order_id>", methods=["DELETE"])
def api_delete_order(order_id):
    database.delete_order(order_id)
    return jsonify({"success": True})


# ── Stats API ─────────────────────────────────────────────────────────────────

@app.route("/api/stats", methods=["GET"])
def api_stats():
    return jsonify(database.get_stats())


# ── Email API ─────────────────────────────────────────────────────────────────

@app.route("/api/email/check", methods=["POST"])
def api_email_check():
    t = threading.Thread(target=run_email_check, daemon=True)
    t.start()
    return jsonify({"success": True})



@app.route("/api/email/status", methods=["GET"])
def api_email_status():
    return jsonify(email_status)


# ── Inventory API ─────────────────────────────────────────────────────────────

@app.route("/api/inventory", methods=["GET"])
def api_get_inventory():
    return jsonify(database.get_inventory())


@app.route("/api/inventory/suggestions", methods=["GET"])
def api_inventory_suggestions():
    return jsonify(database.get_untracked_order_items())


@app.route("/api/inventory", methods=["POST"])
def api_add_inventory():
    item_id = database.add_inventory_item(request.json or {})
    return jsonify({"success": True, "id": item_id}), 201


@app.route("/api/inventory/<int:item_id>", methods=["PUT"])
def api_update_inventory(item_id):
    ok = database.update_inventory_item(item_id, request.json or {})
    return jsonify({"success": ok})


@app.route("/api/inventory/<int:item_id>", methods=["DELETE"])
def api_delete_inventory(item_id):
    database.delete_inventory_item(item_id)
    return jsonify({"success": True})


# ── Sales API ─────────────────────────────────────────────────────────────────

@app.route("/api/sales", methods=["GET"])
def api_get_sales():
    return jsonify(database.get_sales())


@app.route("/api/sales", methods=["POST"])
def api_record_sale():
    sale_id, err = database.record_sale(request.json or {})
    if err:
        return jsonify({"success": False, "error": err}), 400
    return jsonify({"success": True, "id": sale_id}), 201


@app.route("/api/sales/<int:sale_id>", methods=["DELETE"])
def api_delete_sale(sale_id):
    database.delete_sale(sale_id)
    return jsonify({"success": True})


# ── Config API ────────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def api_get_config():
    import copy
    cfg = load_config()
    masked = copy.deepcopy(cfg)
    if masked.get("imap", {}).get("password"):
        masked["imap"]["password"] = "••••••••"
    return jsonify(masked)


@app.route("/api/config", methods=["PUT"])
def api_update_config():
    cfg = load_config()
    data = request.json or {}
    if "imap" in data:
        for k, v in data["imap"].items():
            if k == "password" and v == "••••••••":
                continue
            cfg["imap"][k] = v
    if "merchants" in data:
        cfg["merchants"] = data["merchants"]
    save_config(cfg)
    return jsonify({"success": True})


# ── Startup ───────────────────────────────────────────────────────────────────

def _start():
    database.init_db()
    fixed = database.rebuild_tracking_urls()
    if fixed:
        print(f"Rebuilt tracking URLs for {fixed} order(s)")
    scheduler.start()


if __name__ == "__main__":
    _start()

    # ── Desktop app mode (pywebview) ──────────────────────────────────────────
    if getattr(sys, "frozen", False) or os.environ.get("MARGIN_MATE_DESKTOP"):
        # Force EdgeChromium (WebView2) backend — avoids the pythonnet/WinForms
        # DLL issue on Windows where Python.Runtime.dll fails to initialise.
        os.environ.setdefault("PYWEBVIEW_GUI", "edgechromium")

        try:
            import webview
        except Exception as e:
            print(f"pywebview unavailable ({e}), falling back to browser mode", file=sys.stderr)
            import webbrowser
            port = 5000
            app.run(debug=False, port=port, use_reloader=False)
            sys.exit(0)

        port = _find_free_port()

        flask_thread = threading.Thread(
            target=lambda: app.run(debug=False, port=port, use_reloader=False),
            daemon=True,
        )
        flask_thread.start()

        if not _wait_for_flask(port):
            print("Flask did not start in time", file=sys.stderr)
            sys.exit(1)

        try:
            window = webview.create_window(
                "Margin Mate",
                f"http://localhost:{port}",
                width=1280,
                height=820,
                min_size=(900, 600),
            )
            webview.start()
        except Exception as e:
            # WebView2 not installed — open in default browser instead
            print(f"pywebview failed ({e}), opening in browser", file=sys.stderr)
            import webbrowser
            webbrowser.open(f"http://localhost:{port}")
            # Keep Flask running so the browser tab works
            flask_thread.join()

    # ── Browser / dev mode ────────────────────────────────────────────────────
    else:
        print("Order Tracker running at http://localhost:5000")
        app.run(debug=False, port=5000, use_reloader=False)
