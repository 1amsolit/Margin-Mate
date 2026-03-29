from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import json
import threading
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date().isoformat()
import database
import email_parser as ep
import auspost_tracker

app = Flask(__name__)
CORS(app)

CONFIG_PATH = "config.json"
scheduler = BackgroundScheduler(daemon=True)
email_status = {"last_check": None, "status": "idle", "message": "Not checked yet", "found": 0}
_check_lock = threading.Lock()


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


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


def run_delivery_check():
    try:
        cfg = load_config()
        count = auspost_tracker.run_delivery_check(cfg)
        if count:
            print(f"[Delivery check] {count} order(s) marked delivered")
    except Exception as e:
        print(f"[Delivery check] error: {e}")


def reschedule_checker(cfg):
    interval = cfg.get("imap", {}).get("check_interval_seconds", 300)
    if scheduler.get_job("email_check"):
        scheduler.remove_job("email_check")
    scheduler.add_job(run_email_check, "interval", seconds=interval, id="email_check",
                      misfire_grace_time=60)
    # Delivery check every hour
    if not scheduler.get_job("delivery_check"):
        scheduler.add_job(run_delivery_check, "interval", hours=1, id="delivery_check",
                          misfire_grace_time=300)


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
    ok = database.upsert_order_by_uid(data)
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


@app.route("/api/tracking/check", methods=["POST"])
def api_tracking_check():
    def _run():
        try:
            cfg = load_config()
            count = auspost_tracker.run_delivery_check(cfg)
            print(f"[Delivery check] {count} order(s) marked delivered")
        except Exception as e:
            print(f"[Delivery check] error: {e}")
    threading.Thread(target=_run, daemon=True).start()
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
    cfg = load_config()
    import copy
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
    if "auspost" in data:
        if "auspost" not in cfg:
            cfg["auspost"] = {}
        for k, v in data["auspost"].items():
            cfg["auspost"][k] = v
    save_config(cfg)
    reschedule_checker(cfg)
    return jsonify({"success": True})


# ── Startup ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    database.init_db()
    fixed = database.rebuild_tracking_urls()
    if fixed:
        print(f"Rebuilt tracking URLs for {fixed} order(s)")
    cfg = load_config()
    reschedule_checker(cfg)
    scheduler.start()
    print("Order Tracker running at http://localhost:5000")
    app.run(debug=False, port=5000, use_reloader=False)
