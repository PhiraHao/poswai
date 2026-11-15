"""คืนเงินบางส่วนของบิลที่จ่ายแล้ว

ลูกค้าสั่งห้าจาน จานหนึ่งมาผิด ร้านคืนเงินจานนั้นจานเดียว ของเดิมทำได้อย่างเดียว
คือคืนทั้งบิล แล้วคีย์ใหม่สี่จาน ซึ่งทำให้ยอดขายของวันมีบิลผีเพิ่มหนึ่งใบ ยอด
คืนเงินเกินจริงไปทั้งบิล และคอมมิชชันของพนักงานถูกหักเต็มจำนวนทั้งที่ขายได้สี่จาน

การคืนเงินที่นี่จึงเป็นแถวของตัวเอง ไม่ใช่การเปลี่ยนสถานะบิล บิลหนึ่งใบคืนได้
หลายครั้งจนครบยอด และทุกครั้งรู้ว่าคืนรายการไหน เป็นเงินเท่าไร VAT เท่าไร
ตัวเลข VAT สำคัญเป็นพิเศษ เพราะเป็นเลขที่ต้องลงในใบลดหนี้ตามมาตรา 86/10

ยอดที่คืนถูกหักออกจาก ``pos_orders.net_amount`` ซึ่งเป็น "เงินที่ร้านได้จริง"
ของบิลนั้น รายงานทุกตัวอ่านคอลัมน์นี้อยู่แล้ว ยอดขายจึงถูกต้องทันทีโดยไม่ต้อง
แก้รายงานสักตัว ส่วน ``total_amount`` คือยอดที่ลูกค้าจ่ายตอนนั้น ซึ่งไม่เปลี่ยน
"""
from __future__ import annotations

import json
import sqlite3

import poswai_activity as activity
import poswai_split as split_bills
from poswai_commerce import restore_cancelled_inventory


class RefundError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS order_refunds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        order_no TEXT NOT NULL REFERENCES order_events(order_no),
        branch_id INTEGER NOT NULL,
        subtotal_cents INTEGER NOT NULL DEFAULT 0,
        discount_cents INTEGER NOT NULL DEFAULT 0,
        service_charge_cents INTEGER NOT NULL DEFAULT 0,
        vat_cents INTEGER NOT NULL DEFAULT 0,
        amount_cents INTEGER NOT NULL,
        reason TEXT NOT NULL,
        lines_json TEXT NOT NULL DEFAULT '[]',
        staff_id INTEGER NOT NULL REFERENCES staffs(id),
        approved_by INTEGER,
        created_at TEXT NOT NULL
            DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS order_refunds_by_bill"
                 " ON order_refunds(order_no,created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS order_refunds_by_branch"
                 " ON order_refunds(branch_id,created_at)")


def _row(row) -> dict:
    return {"id": row[0], "order_no": row[1], "branch_id": row[2],
            "subtotal": row[3] / 100, "discount": row[4] / 100,
            "service_charge": row[5] / 100, "vat": row[6] / 100,
            "amount": row[7] / 100, "amount_cents": row[7], "vat_cents": row[6],
            "reason": row[8], "lines": json.loads(row[9]),
            "staff_id": row[10], "approved_by": row[11], "created_at": row[12]}


FIELDS = ("id,order_no,branch_id,subtotal_cents,discount_cents,service_charge_cents,"
          "vat_cents,amount_cents,reason,lines_json,staff_id,approved_by,created_at")


def listing(conn: sqlite3.Connection, *, order_no: str = "", branch_id: int | None = None,
            limit: int = 50) -> list[dict]:
    sql = f"SELECT {FIELDS} FROM order_refunds"
    where, params = [], []
    if order_no:
        where.append("order_no=?")
        params.append(order_no)
    if branch_id is not None:
        where.append("branch_id=?")
        params.append(branch_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    return [_row(row) for row in conn.execute(sql, params)]


def given_back(conn: sqlite3.Connection, order_no: str) -> dict:
    """คืนไปแล้วเท่าไร และคืนรายการไหนไปแล้วกี่ชิ้น"""
    taken: dict[int, int] = {}
    cents = vat = 0
    for row in conn.execute("SELECT amount_cents,vat_cents,lines_json FROM order_refunds"
                            " WHERE order_no=?", (order_no,)):
        cents += row[0]
        vat += row[1]
        for line in json.loads(row[2]):
            taken[int(line["line_id"])] = taken.get(int(line["line_id"]), 0) + int(line["qty"])
    return {"amount_cents": cents, "vat_cents": vat, "by_line": taken}


def refundable(conn: sqlite3.Connection, *, order_no: str, branch_id: int) -> dict:
    """บิลนี้ยังคืนได้เท่าไร และรายการไหนยังเหลือให้คืนกี่ชิ้น

    หน้าจอต้องรู้ก่อนเปิดหน้าต่าง ไม่งั้นพนักงานเลือกของที่คืนไปแล้วแล้วค่อย
    โดนปฏิเสธตอนกดยืนยัน ต่อหน้าลูกค้าที่ยืนรออยู่
    """
    order = split_bills.order_of(conn, order_no, branch_id, status="paid")
    items = split_bills.items_of(conn, order_no)
    done = given_back(conn, order_no)
    lines = []
    for item in items:
        left = int(item["quantity"]) - done["by_line"].get(item["line_id"], 0)
        lines.append({"line_id": item["line_id"], "name": item["name"],
                      "qty": int(item["quantity"]), "left": max(0, left),
                      "price": item["unit_price"], "options": item["options"]})
    # ถ้าบิลนี้เคยออกใบกำกับภาษีไว้ การคืนเงินต้องตามด้วยใบลดหนี้ หน้าจอจึงต้อง
    # รู้ตั้งแต่ก่อนกด ไม่ใช่ให้พนักงานไปจำเองว่าบิลไหนเคยออกใบกำกับ
    invoice = conn.execute("SELECT number FROM tax_invoices WHERE order_no=?"
                           " AND cancelled_at IS NULL", (order_no,)).fetchone()
    return {"order_no": order_no, "table_no": order["table_no"],
            "total": order["total_cents"] / 100,
            "refunded": done["amount_cents"] / 100,
            "left": (order["total_cents"] - done["amount_cents"]) / 100,
            "tax_invoice": invoice[0] if invoice else "",
            "lines": lines}


def _slice_of_whole(order: dict, amount_cents: int) -> dict:
    """คืนเป็นจำนวนเงินเฉย ๆ = คืนบิลนี้ไปทั้งก้อนตามสัดส่วน

    ใช้ตอนลูกค้าไม่ได้ขอคืนจานไหนเป็นพิเศษ แต่ร้านยอมคืนให้ส่วนหนึ่ง
    VAT ต้องแบ่งตามไปด้วย ไม่งั้นใบลดหนี้จะบอกว่าร้านคืนเงินโดยไม่คืนภาษี
    ซึ่งแปลว่าร้านจ่าย VAT ของเงินที่ไม่ได้รับ
    """
    whole = order["total_cents"]
    share = lambda part: split_bills._share([amount_cents, whole - amount_cents], part)[0]
    vat = share(order["vat_cents"])
    service = share(order["service_charge_cents"])
    discount = share(order["discount_cents"])
    return {"subtotal_cents": amount_cents - service - vat + discount,
            "discount_cents": discount, "service_charge_cents": service,
            "vat_cents": vat, "total_cents": amount_cents}


def refund(conn: sqlite3.Connection, *, order_no: str, branch_id: int,
           picks: dict[int, int], amount: float | None, reason: str,
           event_id: str, staff: dict, approver: dict | None = None) -> dict:
    """คืนเงินส่วนหนึ่งของบิลที่จ่ายแล้ว ตามรายการหรือตามจำนวนเงิน

    เลือกรายการได้ หรือบอกจำนวนเงินก็ได้ แต่ไม่ใช่ทั้งสองอย่างพร้อมกัน —
    ถ้าทั้งสองอย่าง จะมีสองคำตอบว่า VAT ที่คืนคือเท่าไร และใบลดหนี้ต้องมีคำตอบเดียว
    """
    if not event_id or len(event_id) > 80:
        raise RefundError("รหัสรายการไม่ถูกต้อง")
    reason = " ".join(str(reason or "").split())[:200]
    if len(reason) < 3:
        raise RefundError("การคืนเงินต้องบอกเหตุผลอย่างน้อย 3 ตัวอักษร")
    prior = conn.execute(f"SELECT {FIELDS} FROM order_refunds WHERE event_id=?",
                         (event_id,)).fetchone()
    if prior:
        # กดซ้ำเพราะเน็ตช้า ไม่ใช่ขอคืนอีกรอบ
        return {"status": "existing", "refund": _row(prior)}
    if picks and amount:
        raise RefundError("เลือกรายการหรือบอกจำนวนเงิน อย่างใดอย่างหนึ่ง")

    order = split_bills.order_of(conn, order_no, branch_id, status="paid")
    paid = conn.execute("SELECT id,net_amount FROM pos_orders WHERE order_no=? AND status='paid'",
                        (order_no,)).fetchone()
    if not paid:
        raise RefundError("บิลนี้ไม่มีการรับเงินที่จะคืน", 409)
    done = given_back(conn, order_no)
    left = order["total_cents"] - done["amount_cents"]
    if left <= 0:
        raise RefundError("บิลนี้คืนเงินครบแล้ว", 409)

    items = split_bills.items_of(conn, order_no)
    by_line = {item["line_id"]: item for item in items}
    lines: list[dict] = []
    if picks:
        for line_id, qty in picks.items():
            item = by_line.get(int(line_id))
            if item is None:
                raise RefundError("รายการที่เลือกไม่อยู่ในบิลนี้", 409)
            qty = int(qty)
            spare = int(item["quantity"]) - done["by_line"].get(item["line_id"], 0)
            if qty < 1 or qty > spare:
                raise RefundError(f"{item['name']} เหลือให้คืนได้ {max(0, spare)} ชิ้น")
            lines.append({"line_id": item["line_id"], "name": item["name"], "qty": qty,
                          "price": item["unit_price"]})
        money = split_bills.parts_of(conn, order, items,
                                     {int(k): int(v) for k, v in picks.items()})[1]
    else:
        cents = round(float(amount or 0) * 100)
        if cents < 1:
            raise RefundError("จำนวนเงินที่คืนต้องมากกว่าศูนย์")
        if cents > left:
            raise RefundError(f"บิลนี้เหลือให้คืนได้อีก {left / 100:,.2f} บาท", 409)
        money = _slice_of_whole(order, cents)
    if money["total_cents"] < 1:
        raise RefundError("รายการที่เลือกคิดเป็นเงินศูนย์บาท ไม่มีอะไรให้คืน")
    if money["total_cents"] > left:
        raise RefundError(f"บิลนี้เหลือให้คืนได้อีก {left / 100:,.2f} บาท", 409)

    cursor = conn.execute(
        "INSERT INTO order_refunds (event_id,order_no,branch_id,subtotal_cents,discount_cents,"
        "service_charge_cents,vat_cents,amount_cents,reason,lines_json,staff_id,approved_by)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (event_id, order_no, branch_id, money["subtotal_cents"], money["discount_cents"],
         money["service_charge_cents"], money["vat_cents"], money["total_cents"], reason,
         json.dumps(lines, ensure_ascii=False), staff["id"],
         approver["id"] if approver else None))

    # เงินที่ร้านได้จริงจากบิลนี้ลดลง รายงานทุกตัวอ่านคอลัมน์นี้อยู่แล้ว
    conn.execute("UPDATE pos_orders SET net_amount=net_amount-? WHERE id=?",
                 (money["total_cents"] / 100, paid[0]))
    # คอมมิชชันของยอดที่ไม่ได้รับแล้ว ต้องถูกหักคืนตามสัดส่วน และเก็บทั้งขาได้
    # ขาคืนไว้ ประวัติค่าแรงจึงอธิบายตัวเองได้โดยไม่ต้องไปอ่านตารางอื่น
    part = money["total_cents"] / order["total_cents"]
    clawed = conn.execute(
        "INSERT INTO commission_records (staff_id,order_id,period_date,base_sales_amount,"
        "calculated_amount,pool_divisor) SELECT staff_id,order_id,period_date,"
        "-base_sales_amount*?,-calculated_amount*?,pool_divisor FROM commission_records"
        " WHERE order_id=? AND calculated_amount>0", (part, part, paid[0])).rowcount

    if lines:
        # ของที่คืนเงินแล้วกลับเข้าสต็อก เฉพาะจำนวนที่คืน ไม่ใช่ทั้งแถว
        _restock(conn, branch_id, by_line, lines)

    if done["amount_cents"] + money["total_cents"] >= order["total_cents"]:
        # คืนจนครบยอดแล้ว บิลนี้เท่ากับถูกคืนทั้งใบ สถานะต้องบอกแบบนั้น
        # ไม่งั้นรายงานยังนับเป็นบิลที่ขายได้ ทั้งที่ร้านไม่ได้เงินสักบาท
        conn.execute("UPDATE order_events SET status='refunded' WHERE order_no=?", (order_no,))
        conn.execute("UPDATE pos_orders SET status='refunded' WHERE id=?", (paid[0],))

    activity.record(conn, branch_id=branch_id, staff=staff, action="refund_partial",
                    subject=f"บิล {order_no}",
                    detail=reason + (f" · อนุมัติโดย {approver['name']}" if approver else ""),
                    amount_cents=money["total_cents"], approved_by=approver["id"] if approver else None)
    kept = conn.execute(f"SELECT {FIELDS} FROM order_refunds WHERE id=?",
                        (cursor.lastrowid,)).fetchone()
    return {"status": "refunded", "refund": _row(kept),
            "left": (left - money["total_cents"]) / 100,
            "commission_entries_reversed": clawed}


def _restock(conn: sqlite3.Connection, branch_id: int, by_line: dict[int, dict],
             lines: list[dict]) -> None:
    """คืนวัตถุดิบของจำนวนที่คืนเงิน

    ``restore_cancelled_inventory`` คืนทั้งบิล ซึ่งถูกสำหรับการคืนเงินทั้งใบ
    แต่ผิดสำหรับการคืนจานเดียวจากห้าจาน จึงคิดตามจำนวนที่คืนจริงตรงนี้
    """
    for line in lines:
        item = by_line[int(line["line_id"])]
        for ingredient in json.loads(item["bom_json"]):
            ingredient_id = ingredient.get("ingId") or ingredient.get("ingredient_id")
            amount = float(ingredient["qty"]) * int(line["qty"])
            conn.execute("UPDATE inventory SET stock=stock+? WHERE branch_id=? AND ingredient_id=?",
                         (amount, branch_id, ingredient_id))


__all__ = ["RefundError", "init", "listing", "given_back", "refundable", "refund",
           "restore_cancelled_inventory"]
