"""Persistent online orders, customer segments and Songwai menu mappings.

All order mutations run in the caller's SQLite transaction. Catalog prices and
recipes always come from POS WAI, never from a partner request or browser.
"""

import datetime
import json
import secrets
import sqlite3

from poswai_catalog import deduct_inventory, quote_order


def init_commerce(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch_id INTEGER NOT NULL,
        line_user_id TEXT,
        songwai_user_id TEXT,
        display_name TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        marketing_opt_in INTEGER NOT NULL DEFAULT 0 CHECK(marketing_opt_in IN (0,1)),
        completed_orders INTEGER NOT NULL DEFAULT 0,
        lifetime_cents INTEGER NOT NULL DEFAULT 0,
        last_order_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS crm_line_identity ON crm_customers(branch_id,line_user_id) WHERE line_user_id IS NOT NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS crm_songwai_identity ON crm_customers(branch_id,songwai_user_id) WHERE songwai_user_id IS NOT NULL")
    conn.execute("""CREATE TABLE IF NOT EXISTS online_orders (
        order_no TEXT PRIMARY KEY REFERENCES order_events(order_no),
        branch_id INTEGER NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('poswai','songwai')),
        external_id TEXT NOT NULL,
        fulfillment TEXT NOT NULL CHECK(fulfillment IN ('self_pickup','rider_pickup')),
        customer_id INTEGER REFERENCES crm_customers(id),
        customer_name TEXT NOT NULL DEFAULT '',
        contact_phone TEXT NOT NULL DEFAULT '',
        pickup_code TEXT NOT NULL,
        payment_status TEXT NOT NULL DEFAULT 'pending',
        status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','accepted','preparing','ready','handed_off','cancelled')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ready_at TEXT,
        handed_off_at TEXT,
        UNIQUE(branch_id,source,external_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS online_orders_queue ON online_orders(branch_id,status,created_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS songwai_menu_map (
        branch_id INTEGER NOT NULL,
        restaurant_id INTEGER NOT NULL,
        songwai_menu_id INTEGER NOT NULL,
        pos_item_id TEXT NOT NULL,
        PRIMARY KEY(branch_id,restaurant_id,songwai_menu_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch_id INTEGER NOT NULL,
        segment TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        created_by INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        sent_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_campaign_deliveries (
        campaign_id INTEGER NOT NULL REFERENCES crm_campaigns(id),
        customer_id INTEGER NOT NULL REFERENCES crm_customers(id),
        status TEXT NOT NULL,
        attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(campaign_id,customer_id)
    )""")


def create_order(
    conn: sqlite3.Connection, *, branch_id: int, source: str, external_id: str,
    fulfillment: str, items: list[dict], customer_id: int | None,
    customer_name: str = "", contact_phone: str = "", payment_status: str = "pending",
) -> dict:
    existing = conn.execute(
        "SELECT order_no,status FROM online_orders WHERE branch_id=? AND source=? AND external_id=?",
        (branch_id, source, external_id),
    ).fetchone()
    if existing:
        return {"order_no": existing[0], "status": existing[1], "existing": True}
    quote = quote_order(conn, branch_id, items)
    deduct_inventory(conn, branch_id, quote["deductions"])
    order_no = "ON-" + secrets.token_hex(10).upper()
    pickup_code = secrets.token_hex(3).upper()
    conn.execute("INSERT INTO order_events(event_id,order_no,branch_id,table_no,total_amount) VALUES(?,?,?,?,?)",
                 ("online:" + order_no, order_no, branch_id,
                  "รับเอง" if fulfillment == "self_pickup" else "ไรเดอร์", quote["total_amount"]))
    for item in quote["items"]:
        conn.execute("""INSERT INTO order_items
            (order_no,item_id,name,quantity,unit_price,bom_json,station,course_mode)
            VALUES(?,?,?,?,?,?,?,?)""",
            (order_no, item["id"], item["name"], item["qty"], item["price"],
             json.dumps(item["bom"]), item["station"], "FIRE"))
    for station in {item["station"] for item in quote["items"]}:
        conn.execute("INSERT INTO kds_station_tickets(order_no,station,status) VALUES(?,?,'queued')",
                     (order_no, station))
    conn.execute("""INSERT INTO online_orders
        (order_no,branch_id,source,external_id,fulfillment,customer_id,customer_name,
         contact_phone,pickup_code,payment_status) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (order_no, branch_id, source, external_id, fulfillment, customer_id,
         customer_name, contact_phone, pickup_code, payment_status))
    return {"order_no": order_no, "status": "new", "existing": False,
            "pickup_code": pickup_code, "total_amount": quote["total_amount"]}


def upsert_customer(
    conn: sqlite3.Connection, *, branch_id: int, source: str, external_id: str,
    display_name: str = "", phone: str = "", marketing_opt_in: bool | None = None,
) -> int:
    column = "line_user_id" if source == "line" else "songwai_user_id"
    row = conn.execute(f"SELECT id FROM crm_customers WHERE branch_id=? AND {column}=?",
                       (branch_id, external_id)).fetchone()
    if row:
        changes = ["updated_at=CURRENT_TIMESTAMP"]
        values: list = []
        if display_name:
            changes.append("display_name=?")
            values.append(display_name)
        if phone:
            changes.append("phone=?")
            values.append(phone)
        if marketing_opt_in is not None and source == "line":
            changes.append("marketing_opt_in=?")
            values.append(int(marketing_opt_in))
        conn.execute(f"UPDATE crm_customers SET {','.join(changes)} WHERE id=?", (*values, row[0]))
        return row[0]
    cursor = conn.execute(
        f"INSERT INTO crm_customers(branch_id,{column},display_name,phone,marketing_opt_in) VALUES(?,?,?,?,?)",
        (branch_id, external_id, display_name, phone,
         int(marketing_opt_in) if source == "line" and marketing_opt_in is not None else 0),
    )
    return cursor.lastrowid


def segment_for(row: sqlite3.Row, today: datetime.date | None = None) -> str:
    if not row["completed_orders"]:
        return "new"
    if row["last_order_at"]:
        last = datetime.date.fromisoformat(row["last_order_at"][:10])
        if (today or datetime.date.today()) - last > datetime.timedelta(days=30):
            return "dormant30"
    return "returning" if row["completed_orders"] >= 2 else "new"


def list_customers(conn: sqlite3.Connection, branch_id: int, segment: str = "all") -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""SELECT id,display_name,phone,marketing_opt_in,completed_orders,
        lifetime_cents,last_order_at,CASE WHEN line_user_id IS NULL THEN 0 ELSE 1 END AS line_linked,
        CASE WHEN songwai_user_id IS NOT NULL THEN 'Songwai' ELSE 'LINE' END AS source
        FROM crm_customers WHERE branch_id=? ORDER BY COALESCE(last_order_at,created_at) DESC LIMIT 1000""",
        (branch_id,)).fetchall()
    result = []
    for row in rows:
        group = segment_for(row)
        if segment not in ("all", group):
            continue
        result.append({**dict(row), "segment": group, "lifetime_amount": row["lifetime_cents"] / 100})
    return result


def mark_handed_off(conn: sqlite3.Connection, order_no: str) -> bool:
    row = conn.execute("SELECT customer_id FROM online_orders WHERE order_no=? AND status!='cancelled'",
                       (order_no,)).fetchone()
    if not row:
        return False
    changed = conn.execute("""UPDATE online_orders SET status='handed_off',handed_off_at=CURRENT_TIMESTAMP
        WHERE order_no=? AND status!='handed_off'""", (order_no,)).rowcount
    if changed and row[0]:
        amount = conn.execute("SELECT total_amount FROM order_events WHERE order_no=?", (order_no,)).fetchone()[0]
        conn.execute("""UPDATE crm_customers SET completed_orders=completed_orders+1,
            lifetime_cents=lifetime_cents+?,last_order_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP WHERE id=?""", (round(amount * 100), row[0]))
    return bool(changed)


def restore_cancelled_inventory(conn: sqlite3.Connection, branch_id: int, order_no: str) -> None:
    """Put BOM quantities back exactly once while the status transaction is open."""
    for quantity, bom_json in conn.execute(
        "SELECT quantity,bom_json FROM order_items WHERE order_no=?", (order_no,)
    ):
        for ingredient in json.loads(bom_json):
            ingredient_id = ingredient.get("ingId") or ingredient.get("ingredient_id")
            amount = float(ingredient["qty"]) * quantity
            conn.execute("UPDATE inventory SET stock=stock+? WHERE branch_id=? AND ingredient_id=?",
                         (amount, branch_id, ingredient_id))
