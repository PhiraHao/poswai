"""Audited, idempotent inventory movements for one SQLite transaction.

The caller authenticates the staff role and owns BEGIN IMMEDIATE/commit/rollback.
This module never simulates suppliers, purchase orders, or physical locations.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation


class InventoryError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _positive_qty(value: object) -> float:
    if isinstance(value, bool):
        raise InventoryError("Invalid quantity")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InventoryError("Invalid quantity") from None
    if not amount.is_finite() or amount <= 0 or amount > 1_000_000_000 or amount.as_tuple().exponent < -6:
        raise InventoryError("Invalid quantity")
    return float(amount)


def _identifier(value: object, field: str, length: int = 80) -> str:
    result = str(value or "").strip()
    if not result or len(result) > length:
        raise InventoryError(f"Invalid {field}")
    return result


def _branch(value: object) -> int:
    if isinstance(value, bool):
        raise InventoryError("Invalid branch")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise InventoryError("Invalid branch") from None
    if result <= 0 or str(result) != str(value):
        raise InventoryError("Invalid branch")
    return result


def init_inventory_movements(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS inventory_movements (
        event_id TEXT PRIMARY KEY,
        branch_id INTEGER NOT NULL,
        ingredient_id TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('restock','waste','transfer')),
        quantity REAL NOT NULL CHECK(quantity > 0),
        target_branch_id INTEGER,
        previous_stock REAL NOT NULL,
        resulting_stock REAL NOT NULL,
        actor_staff_id INTEGER NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS inventory_movements_branch_time ON inventory_movements(branch_id,created_at)")


def apply_inventory_movement(
    conn: sqlite3.Connection, *, event_id: str, branch_id: int,
    ingredient_id: str, action: str, quantity: object,
    actor_staff_id: int, target_branch_id: int | None = None,
    note: str = "",
) -> dict:
    """Apply one audited movement, or return the exact prior event unchanged.

    ``transfer`` creates linked debit and credit rows using event IDs
    ``<event_id>`` and ``<event_id>:receive``. Branches must exist. Missing or
    insufficient source stock is rejected rather than clamped below zero.
    """
    event_id = _identifier(event_id, "event id", 100)
    branch_id = _branch(branch_id)
    ingredient_id = _identifier(ingredient_id, "ingredient id")
    if action not in {"restock", "waste", "transfer"}:
        raise InventoryError("Invalid inventory action")
    quantity = _positive_qty(quantity)
    if isinstance(actor_staff_id, bool) or not isinstance(actor_staff_id, int) or actor_staff_id < 1:
        raise InventoryError("Invalid staff")
    if not isinstance(note, str) or len(note) > 500:
        raise InventoryError("Invalid note")
    note = note.strip()
    if action == "transfer":
        target_branch_id = _branch(target_branch_id)
        if target_branch_id == branch_id:
            raise InventoryError("Destination must be another branch")
    elif target_branch_id is not None:
        raise InventoryError("Destination is allowed only for transfers")

    existing = conn.execute("""SELECT branch_id,ingredient_id,action,quantity,target_branch_id,
        previous_stock,resulting_stock,actor_staff_id,note FROM inventory_movements WHERE event_id=?""",
        (event_id,)).fetchone()
    if existing:
        if (existing[0] != branch_id or existing[1] != ingredient_id or existing[2] != action
                or existing[3] != quantity or existing[4] != target_branch_id
                or existing[7] != actor_staff_id or existing[8] != note):
            raise InventoryError("Event id already used for another inventory movement", 409)
        return {"status": "existing", "event_id": event_id,
                "branch_id": branch_id, "ingredient_id": ingredient_id,
                "stock": existing[6], "previous_stock": existing[5]}

    if not conn.execute("SELECT 1 FROM branches WHERE id=?", (branch_id,)).fetchone():
        raise InventoryError("Source branch does not exist", 404)
    if target_branch_id and not conn.execute("SELECT 1 FROM branches WHERE id=?", (target_branch_id,)).fetchone():
        raise InventoryError("Destination branch does not exist", 404)
    previous_row = conn.execute("SELECT stock FROM inventory WHERE branch_id=? AND ingredient_id=?",
                                (branch_id, ingredient_id)).fetchone()
    previous = float(previous_row[0]) if previous_row else 0.0
    if action == "restock":
        resulting = previous + quantity
        if resulting < 0 or resulting > 1_000_000_000:
            raise InventoryError("Resulting stock is outside allowed range", 409)
        conn.execute("""INSERT INTO inventory(branch_id,ingredient_id,stock) VALUES (?,?,?)
            ON CONFLICT(branch_id,ingredient_id) DO UPDATE SET stock=excluded.stock""",
            (branch_id, ingredient_id, resulting))
    else:
        cursor = conn.execute("""UPDATE inventory SET stock=stock-? WHERE
            branch_id=? AND ingredient_id=? AND stock>=?""",
            (quantity, branch_id, ingredient_id, quantity))
        if cursor.rowcount != 1:
            raise InventoryError("Insufficient stock", 409)
        resulting = previous - quantity
    conn.execute("""INSERT INTO inventory_movements
        (event_id,branch_id,ingredient_id,action,quantity,target_branch_id,
         previous_stock,resulting_stock,actor_staff_id,note)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (event_id, branch_id, ingredient_id, action, quantity, target_branch_id,
         previous, resulting, actor_staff_id, note))

    if action == "transfer":
        target_row = conn.execute("SELECT stock FROM inventory WHERE branch_id=? AND ingredient_id=?",
                                  (target_branch_id, ingredient_id)).fetchone()
        target_previous = float(target_row[0]) if target_row else 0.0
        target_result = target_previous + quantity
        if target_result > 1_000_000_000:
            raise InventoryError("Destination stock exceeds limit")
        conn.execute("""INSERT INTO inventory(branch_id,ingredient_id,stock) VALUES (?,?,?)
            ON CONFLICT(branch_id,ingredient_id) DO UPDATE SET stock=excluded.stock""",
            (target_branch_id, ingredient_id, target_result))
        conn.execute("""INSERT INTO inventory_movements
            (event_id,branch_id,ingredient_id,action,quantity,target_branch_id,
             previous_stock,resulting_stock,actor_staff_id,note)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (event_id + ":receive", target_branch_id, ingredient_id, "transfer",
             quantity, branch_id, target_previous, target_result, actor_staff_id, note))
    return {"status": "applied", "event_id": event_id,
            "branch_id": branch_id, "ingredient_id": ingredient_id,
            "stock": resulting, "previous_stock": previous}


def list_inventory_movements(conn: sqlite3.Connection, branch_id: int, limit: int = 100) -> list[dict]:
    branch_id = _branch(branch_id)
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise InventoryError("Invalid limit")
    rows = conn.execute("""SELECT event_id,ingredient_id,action,quantity,target_branch_id,
        previous_stock,resulting_stock,actor_staff_id,note,created_at
        FROM inventory_movements WHERE branch_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?""",
        (branch_id, limit)).fetchall()
    return [dict(zip(("event_id", "ingredient_id", "action", "quantity", "target_branch_id",
                      "previous_stock", "resulting_stock", "actor_staff_id", "note", "created_at"), row))
            for row in rows]
