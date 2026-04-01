import os
import sqlite3
import json
from datetime import datetime, timezone

import paths


def _now():
    return datetime.now(timezone.utc).isoformat()

DB_PATH = os.path.join(paths.get_data_dir(), "orders.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant TEXT NOT NULL,
            order_number TEXT,
            status TEXT DEFAULT 'confirmed',
            item_description TEXT,
            amount REAL,
            currency TEXT DEFAULT 'AUD',
            order_date TEXT,
            shipped_date TEXT,
            tracking_number TEXT,
            tracking_url TEXT,
            carrier TEXT,
            email_subject TEXT,
            email_from TEXT,
            email_received_date TEXT,
            email_uid TEXT UNIQUE,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            sku TEXT,
            category TEXT,
            quantity INTEGER DEFAULT 0,
            cost_price REAL DEFAULT 0,
            sale_price REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id INTEGER,
            product_name TEXT,
            quantity_sold INTEGER DEFAULT 1,
            sale_price REAL,
            cost_price REAL,
            sale_date TEXT,
            order_ref TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inventory_id) REFERENCES inventory(id)
        );
    """)
    conn.commit()
    conn.close()


# ── Orders ────────────────────────────────────────────────────────────────────

def get_orders(status=None, merchant=None, search=None):
    conn = get_conn()
    c = conn.cursor()
    sql = "SELECT * FROM orders WHERE 1=1"
    params = []
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    if merchant and merchant != "all":
        sql += " AND merchant = ?"
        params.append(merchant)
    if search:
        sql += " AND (order_number LIKE ? OR item_description LIKE ? OR tracking_number LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    sql += " ORDER BY created_at DESC"
    rows = c.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_order(order_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_order_by_uid(data: dict):
    """Insert a new order or update status if a better status arrived."""
    conn = get_conn()
    c = conn.cursor()
    existing = c.execute(
        "SELECT * FROM orders WHERE email_uid = ?", (data.get("email_uid"),)
    ).fetchone()

    if existing:
        conn.close()
        return False  # duplicate

    # Check if same order number already exists and we should upgrade status
    order_number = data.get("order_number")
    merchant = data.get("merchant")
    new_status = data.get("status", "confirmed")
    STATUS_RANK = {"confirmed": 1, "shipped": 2, "delivered": 3, "cancelled": 4, "refunded": 4}

    if order_number and merchant:
        existing_order = c.execute(
            "SELECT * FROM orders WHERE order_number = ? AND merchant = ? ORDER BY created_at DESC LIMIT 1",
            (order_number, merchant),
        ).fetchone()
        if existing_order:
            old_status = existing_order["status"]
            if STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(old_status, 0):
                update_fields = {
                    "status": new_status,
                    "email_uid": data.get("email_uid"),
                    "updated_at": _now(),
                }
                if new_status == "shipped":
                    update_fields["shipped_date"] = data.get("shipped_date") or _now()
                    update_fields["tracking_number"] = data.get("tracking_number")
                    update_fields["tracking_url"] = data.get("tracking_url")
                    update_fields["carrier"] = data.get("carrier")
                elif new_status in ("cancelled", "refunded"):
                    pass  # just status update

                set_clause = ", ".join(f"{k} = ?" for k in update_fields)
                vals = list(update_fields.values()) + [existing_order["id"]]
                c.execute(f"UPDATE orders SET {set_clause} WHERE id = ?", vals)
                conn.commit()
                conn.close()
                return True
            else:
                # Just record the uid so we don't reprocess
                conn.close()
                return False

    # Insert new order
    cols = [
        "merchant", "order_number", "status", "item_description", "amount", "currency",
        "order_date", "shipped_date", "tracking_number", "tracking_url", "carrier",
        "email_subject", "email_from", "email_received_date", "email_uid", "notes",
    ]
    vals = [data.get(col) for col in cols]
    placeholders = ", ".join("?" for _ in cols)
    c.execute(f"INSERT INTO orders ({', '.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()
    conn.close()
    return True


def update_order(order_id, data: dict):
    conn = get_conn()
    data["updated_at"] = _now()
    allowed = [
        "status", "order_number", "item_description", "amount", "currency",
        "order_date", "shipped_date", "tracking_number", "tracking_url",
        "carrier", "notes", "updated_at",
    ]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [order_id]
    conn.execute(f"UPDATE orders SET {set_clause} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_order(order_id):
    conn = get_conn()
    conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()


# ── Inventory ─────────────────────────────────────────────────────────────────

def get_inventory():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM inventory ORDER BY product_name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_untracked_order_items():
    """Return distinct item_descriptions from orders not yet in inventory."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT item_description, merchant, order_date
        FROM orders
        WHERE item_description IS NOT NULL AND item_description != ''
          AND item_description NOT IN (SELECT product_name FROM inventory)
        ORDER BY item_description
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_inventory_item(data: dict):
    conn = get_conn()
    c = conn.cursor()
    cols = ["product_name", "sku", "category", "quantity", "cost_price", "sale_price", "notes"]
    vals = [data.get(col) for col in cols]
    c.execute(
        f"INSERT INTO inventory ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        vals,
    )
    item_id = c.lastrowid
    conn.commit()
    conn.close()
    return item_id


def update_inventory_item(item_id, data: dict):
    conn = get_conn()
    data["updated_at"] = _now()
    allowed = ["product_name", "sku", "category", "quantity", "cost_price", "sale_price", "notes", "updated_at"]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [item_id]
    conn.execute(f"UPDATE inventory SET {set_clause} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_inventory_item(item_id):
    conn = get_conn()
    conn.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


# ── Sales ─────────────────────────────────────────────────────────────────────

def record_sale(data: dict):
    conn = get_conn()
    c = conn.cursor()

    item = c.execute("SELECT * FROM inventory WHERE id = ?", (data["inventory_id"],)).fetchone()
    if not item:
        conn.close()
        return None, "Item not found"

    qty = int(data.get("quantity_sold", 1))
    if item["quantity"] < qty:
        conn.close()
        return None, f"Only {item['quantity']} in stock"

    sale_price = float(data.get("sale_price", item["sale_price"]))
    cost_price = float(item["cost_price"])

    c.execute(
        """INSERT INTO sales
           (inventory_id, product_name, quantity_sold, sale_price, cost_price, sale_date, order_ref, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item["id"],
            item["product_name"],
            qty,
            sale_price,
            cost_price,
            data.get("sale_date") or datetime.utcnow().date().isoformat(),
            data.get("order_ref"),
            data.get("notes"),
        ),
    )
    c.execute(
        "UPDATE inventory SET quantity = quantity - ?, updated_at = ? WHERE id = ?",
        (qty, _now(), item["id"]),
    )
    sale_id = c.lastrowid
    conn.commit()
    conn.close()
    return sale_id, None


def get_sales():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sales ORDER BY sale_date DESC, created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fill_missing_items(email_uid, item_description=None, order_date=None):
    """Backfill item_description and/or order_date for an already-recorded order."""
    if not item_description and not order_date:
        return False
    conn = get_conn()
    if item_description:
        conn.execute(
            """UPDATE orders SET item_description = ?, updated_at = ?
               WHERE email_uid = ?""",
            (item_description, _now(), email_uid),
        )
    if order_date:
        conn.execute(
            """UPDATE orders SET order_date = ?, updated_at = ?
               WHERE email_uid = ?
               AND (order_date IS NULL OR order_date = '' OR order_date LIKE '2026-03-17%')""",
            (order_date, _now(), email_uid),
        )
    conn.commit()
    conn.close()
    return True


def fill_missing_tracking(email_uid, tracking_number, carrier, tracking_url):
    """Backfill tracking data — always update tracking_url/carrier if we now have them."""
    if not tracking_number:
        return False
    conn = get_conn()
    conn.execute(
        """UPDATE orders SET
               tracking_number = ?,
               carrier = COALESCE(?, carrier),
               tracking_url = COALESCE(?, tracking_url),
               updated_at = ?
           WHERE email_uid = ?""",
        (tracking_number, carrier, tracking_url, _now(), email_uid),
    )
    # Also patch any order that shares the same tracking_number but has no URL yet
    if tracking_url:
        conn.execute(
            """UPDATE orders SET
                   carrier = COALESCE(carrier, ?),
                   tracking_url = ?,
                   updated_at = ?
               WHERE tracking_number = ?
               AND (tracking_url IS NULL OR tracking_url = '')""",
            (carrier, tracking_url, _now(), tracking_number),
        )
    conn.commit()
    conn.close()
    return True


# Carrier name → tracking URL template
_CARRIER_URL_TEMPLATES = {
    "Australia Post":   "https://auspost.com.au/mypost/track/#/details/{}",
    "StarTrack":        "https://startrack.com.au/track-and-trace/?ref={}",
    "Couriers Please":  "https://couriersplease.com.au/Track/Summary?consignmentNumber={}",
    "Amazon Logistics": "https://track.amazon.com.au/tracking/{}",
    "FedEx":            "https://www.fedex.com/apps/fedextrack/?tracknumbers={}",
    "DHL":              "https://www.dhl.com/au-en/home/tracking.html?tracking-id={}",
    "UPS":              "https://www.ups.com/track?tracknum={}",
    "Sendle":           "https://track.sendle.com/tracking?ref={}",
    "Aramex/Fastway":   "https://www.aramex.com.au/tools/track?l={}",
    "Hunter Express":   "https://www.hunterexpress.com.au/track?ref={}",
    "TNT":              "https://www.tnt.com/express/en_au/site/shipping-tools/tracking.html?searchType=CON&cons={}",
    "GoPeople":         "https://www.gopeople.com.au/tracking/?code={}",
}


def rebuild_tracking_urls():
    """Fix any shipped orders that have a carrier but are missing a tracking URL."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, tracking_number, carrier FROM orders
           WHERE status = 'shipped'
           AND tracking_number IS NOT NULL AND tracking_number != ''
           AND (tracking_url IS NULL OR tracking_url = '')
           AND carrier IS NOT NULL AND carrier != ''"""
    ).fetchall()
    for row in rows:
        tpl = _CARRIER_URL_TEMPLATES.get(row["carrier"])
        if tpl:
            conn.execute(
                "UPDATE orders SET tracking_url = ?, updated_at = ? WHERE id = ?",
                (tpl.format(row["tracking_number"]), _now(), row["id"]),
            )
    conn.commit()
    conn.close()
    return len(rows)


def delete_sale(sale_id):
    conn = get_conn()
    # Restore inventory quantity
    sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale and sale["inventory_id"]:
        conn.execute(
            "UPDATE inventory SET quantity = quantity + ?, updated_at = ? WHERE id = ?",
            (sale["quantity_sold"], _now(), sale["inventory_id"]),
        )
    conn.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
    conn.commit()
    conn.close()


def get_stats():
    conn = get_conn()
    c = conn.cursor()

    orders_total = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    orders_confirmed = c.execute("SELECT COUNT(*) FROM orders WHERE status='confirmed'").fetchone()[0]
    orders_shipped = c.execute("SELECT COUNT(*) FROM orders WHERE status='shipped'").fetchone()[0]
    orders_delivered = c.execute("SELECT COUNT(*) FROM orders WHERE status='delivered'").fetchone()[0]
    orders_cancelled = c.execute("SELECT COUNT(*) FROM orders WHERE status IN ('cancelled','refunded')").fetchone()[0]

    revenue = c.execute("SELECT COALESCE(SUM(sale_price * quantity_sold), 0) FROM sales").fetchone()[0]
    cost = c.execute("SELECT COALESCE(SUM(cost_price * quantity_sold), 0) FROM sales").fetchone()[0]
    profit = revenue - cost
    margin = (profit / revenue * 100) if revenue > 0 else 0

    inv_value = c.execute(
        "SELECT COALESCE(SUM(cost_price * quantity), 0) FROM inventory"
    ).fetchone()[0]
    inv_items = c.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]

    conn.close()
    return {
        "orders_total": orders_total,
        "orders_confirmed": orders_confirmed,
        "orders_shipped": orders_shipped,
        "orders_delivered": orders_delivered,
        "orders_cancelled": orders_cancelled,
        "revenue": round(revenue, 2),
        "cost": round(cost, 2),
        "profit": round(profit, 2),
        "margin_pct": round(margin, 2),
        "inventory_value": round(inv_value, 2),
        "inventory_items": inv_items,
    }
