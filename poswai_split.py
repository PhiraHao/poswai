"""แยกบิล ย้ายโต๊ะ และรวมบิล

ร้านอาหารไทยเจอสามเรื่องนี้ทุกวัน: โต๊ะหนึ่งนั่งหกคนแล้วขอจ่ายแยก ลูกค้าย้ายจาก
โต๊ะ 3 ไปโต๊ะ 7 เพราะแดด และสองโต๊ะที่มาด้วยกันขอจ่ายรวมใบเดียว ของเดิมทำไม่ได้
เลยทั้งสามเรื่อง ทางออกที่ร้านใช้คือยกเลิกบิลแล้วคีย์ใหม่ ซึ่งทำให้ยอดขายของวัน
มีบิลผีเพิ่มขึ้นทุกครั้ง และครัวได้ตั๋วซ้ำของอาหารที่ทำเสร็จไปแล้ว

หลักการของไฟล์นี้: หลังแยกแล้วทั้งสองใบต้องเป็นบิลธรรมดาที่ปิดได้ พิมพ์ใบเสร็จได้
ออกใบกำกับภาษีได้ เหมือนบิลที่คีย์มาตรง ๆ จึงไม่มีตารางใหม่ ไม่มีสถานะพิเศษ
มีแค่ order_events อีกแถวกับ order_items ที่ย้ายไปอยู่กับมัน

เรื่องยอดเงิน: ไม่คิดใหม่จากเมนูวันนี้ แต่ "แบ่ง" ยอดที่บันทึกไว้แล้วออกเป็นสองก้อน
ด้วยวิธีเศษมากได้ก่อน ผลรวมของสองใบจึงเท่ากับใบเดิมทุกสตางค์ ถ้าคิดใหม่
ร้านที่แก้ราคาเมนูหรือเปลี่ยนอัตราค่าบริการระหว่างวันจะเก็บเงินได้ไม่เท่าที่ตกลงไว้
"""
from __future__ import annotations

import sqlite3

import poswai_activity as activity


class SplitError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


ORDER_FIELDS = ("order_no", "branch_id", "table_no", "total_amount", "status", "note",
                "ordered_by", "customer_id", "subtotal_cents", "discount_cents",
                "service_charge_cents", "vat_cents", "discount_reason")

ITEM_FIELDS = ("line_id", "item_id", "name", "quantity", "unit_price", "bom_json",
               "station", "course_mode", "options", "unit_cost", "discount_cents")

# ตั๋วครัวที่ "ทำน้อยที่สุด" คือสถานะที่ต้องชนะตอนรวมบิล ไม่งั้นอาหารที่ยังไม่ได้ทำ
# จะหายไปจากจอครัวเพราะอีกใบกดว่าเสร็จแล้ว
TICKET_ORDER = {"held": 0, "queued": 1, "ready": 2}


def _share(weights: list[int], amount: int) -> list[int]:
    """แบ่งยอดก้อนเดียวตามน้ำหนัก ให้ผลรวมเท่าของเดิมทุกสตางค์

    เศษมากได้ก่อน เหมือน profile.split_discount แต่ที่นี่น้ำหนักรวมเป็นศูนย์ได้
    (เช่นค่าบริการที่ไม่มีรายการไหนในบิลต้องเสีย แต่คอลัมน์ยังมีเลขค้างอยู่)
    กรณีนั้นยอดทั้งก้อนอยู่กับก้อนแรก เพราะเงินหายไปเฉย ๆ ไม่ได้
    """
    if not weights:
        return []
    amount = int(amount)
    if amount == 0:
        return [0] * len(weights)
    total = sum(weights)
    if total <= 0:
        return [amount] + [0] * (len(weights) - 1)
    exact = [weight * amount / total for weight in weights]
    shares = [int(value) for value in exact]
    short = amount - sum(shares)
    for index in sorted(range(len(exact)), key=lambda i: exact[i] - shares[i],
                        reverse=True)[:short]:
        shares[index] += 1
    return shares


def order_of(conn: sqlite3.Connection, order_no: str, branch_id: int, *,
             status: str = "open") -> dict:
    """บิลหนึ่งใบพร้อมรายละเอียดยอดที่ตรวจแล้วว่าประกอบกันเป็นยอดรวมจริง

    ``status`` คือสถานะที่ยอมรับ — การแยกบิลต้องการบิลที่ยังเปิด การคืนเงิน
    ต้องการบิลที่จ่ายแล้ว ทั้งคู่ต้องการการตรวจชุดเดียวกันก่อนแตะยอด
    """
    row = conn.execute(f"SELECT {','.join(ORDER_FIELDS)} FROM order_events WHERE order_no=?",
                       (order_no,)).fetchone()
    # สาขาที่ไม่ตรงตอบ 404 เหมือนไม่มีบิลนี้ ไม่ใช่ 403 — 403 เท่ากับยืนยันว่าบิลมีจริง
    if row is None or row[1] != branch_id:
        raise SplitError("ไม่พบบิลนี้", 404)
    order = dict(zip(ORDER_FIELDS, row))
    if order["status"] != status:
        raise SplitError("บิลนี้ปิดแล้ว แยกหรือย้ายไม่ได้" if status == "open"
                         else "บิลนี้ยังไม่ได้รับเงิน คืนเงินไม่ได้", 409)
    if conn.execute("SELECT 1 FROM online_orders WHERE order_no=?", (order_no,)).fetchone():
        raise SplitError("บิลสั่งออนไลน์ไม่ใช่บิลโต๊ะ แยกหรือรวมไม่ได้", 409)
    if conn.execute("SELECT 1 FROM offline_sales WHERE order_no=?", (order_no,)).fetchone():
        # บิลที่ขายตอนเน็ตล่มเก็บ "เงินที่รับมาจริง" ไม่ใช่ยอดที่กฎร้านคิดได้
        # รายละเอียดยอดจึงไม่ประกอบกันเป็นยอดรวม แบ่งแล้วจะได้เลขที่ไม่มีใครตรวจได้
        raise SplitError("บิลที่ขายตอนออฟไลน์ต้องให้ผู้จัดการตรวจก่อน แยกหรือคืนเงินบางส่วนไม่ได้", 409)
    total_cents = round(float(order["total_amount"]) * 100)
    parts = (order["subtotal_cents"] - order["discount_cents"]
             + order["service_charge_cents"] + order["vat_cents"])
    if order["subtotal_cents"] <= 0 or parts != total_cents:
        # บิลเก่าก่อนระบบเก็บรายละเอียดยอด มีแต่ยอดรวม แบ่งแล้วจะไม่รู้ว่า VAT
        # ของแต่ละใบเท่าไร ซึ่งเป็นเลขที่ต้องพิมพ์ลงใบเสร็จ
        raise SplitError("บิลนี้ไม่มีรายละเอียดยอดครบ แยกบิลหรือคืนเงินบางส่วนไม่ได้ "
                         "ให้ทำที่หน้าเคาน์เตอร์แล้วจดไว้แทน", 409)
    order["total_cents"] = total_cents
    return order


def items_of(conn: sqlite3.Connection, order_no: str) -> list[dict]:
    rows = conn.execute(f"SELECT rowid,{','.join(ITEM_FIELDS[1:])} FROM order_items"
                        " WHERE order_no=? ORDER BY rowid", (order_no,)).fetchall()
    if not rows:
        raise SplitError("บิลนี้ไม่มีรายการอาหาร", 409)
    return [dict(zip(ITEM_FIELDS, row)) for row in rows]


def _bearing(conn: sqlite3.Connection, branch_id: int, items: list[dict]) -> dict[str, tuple[bool, bool]]:
    """เมนูแต่ละตัวต้องเสียค่าบริการและ VAT หรือไม่ ตามที่ร้านตั้งไว้

    ต้องรู้เพราะน้ำแข็งที่ร้านตั้งว่าไม่คิดค่าบริการ ไม่ควรถูกแบ่งค่าบริการมาใส่
    เมนูที่ถูกลบไปแล้วถือว่าเสียทั้งสองอย่าง ซึ่งเป็นค่าตั้งต้นของทุกเมนู
    """
    answer: dict[str, tuple[bool, bool]] = {}
    for item in items:
        row = conn.execute("SELECT tax_mode,service_charge FROM menu_catalog"
                           " WHERE branch_id=? AND item_id=?",
                           (branch_id, item["item_id"])).fetchone()
        answer[item["item_id"]] = (True, True) if row is None else (row[0] != "none", bool(row[1]))
    return answer


def _queue_no(conn: sqlite3.Connection, branch_id: int) -> int:
    return conn.execute("SELECT COALESCE(MAX(queue_no),0)+1 FROM order_events"
                        " WHERE branch_id=? AND date(created_at)=date('now')",
                        (branch_id,)).fetchone()[0]


def _ticket_rows(conn: sqlite3.Connection, order_no: str) -> dict[str, tuple]:
    return {row[0]: row for row in conn.execute(
        "SELECT station,status,created_at,fired_at,ready_at FROM kds_station_tickets"
        " WHERE order_no=?", (order_no,))}


def _write_totals(conn: sqlite3.Connection, order_no: str, money: dict) -> None:
    conn.execute("UPDATE order_events SET total_amount=?,subtotal_cents=?,discount_cents=?,"
                 "service_charge_cents=?,vat_cents=? WHERE order_no=?",
                 (money["total_cents"] / 100, money["subtotal_cents"], money["discount_cents"],
                  money["service_charge_cents"], money["vat_cents"], order_no))


def _summary(order_no: str, table_no: str, money: dict) -> dict:
    return {"order_no": order_no, "table_no": table_no,
            "total_amount": money["total_cents"] / 100,
            "totals": {"subtotal": money["subtotal_cents"] / 100,
                       "discount": money["discount_cents"] / 100,
                       "service_charge": money["service_charge_cents"] / 100,
                       "vat": money["vat_cents"] / 100}}


def parts_of(conn: sqlite3.Connection, order: dict, items: list[dict],
             picks: dict[int, int]) -> tuple[dict, dict, list[tuple[dict, int, int, int]]]:
    """แบ่งยอดของบิลหนึ่งออกเป็นสองก้อน: ที่เหลือ กับที่เลือกไว้

    ทั้งการแยกบิลและการคืนเงินบางส่วนถามคำถามเดียวกัน — "ของชุดนี้คิดเป็นเงิน
    เท่าไรของบิลนี้" — จึงต้องตอบด้วยเลขชุดเดียวกัน ไม่งั้นแยกบิลแล้วคืนเงินใบ
    ที่แยกออกมา จะได้ยอดคนละตัวกับคืนรายการเดียวกันจากบิลเดิม

    คืน (ยอดที่เหลือ, ยอดที่เลือก, รายการที่ถูกเลือกพร้อมส่วนลดที่แบ่งแล้ว)
    """
    branch_id = order["branch_id"]
    bearing = _bearing(conn, branch_id, items)
    # สองก้อน: [0] อยู่กับบิลเดิม [1] ไปบิลใหม่
    gross = [0, 0]
    line_off = [0, 0]
    service_weight = [0, 0]
    vat_weight = [0, 0]
    moves: list[tuple[dict, int, int, int]] = []   # (item, move_qty, move_off, stay_off)
    for item in items:
        quantity = int(item["quantity"])
        move_qty = int(picks.get(item["line_id"], 0))
        per = round(float(item["unit_price"]) * 100)
        whole_off = int(item["discount_cents"] or 0)
        # ส่วนลดของรายการเป็นของทั้งแถว แบ่งตามจำนวนที่ย้าย เศษอยู่กับบิลเดิม
        move_off = whole_off * move_qty // quantity
        stay_off = whole_off - move_off
        for part, qty, off in ((1, move_qty, move_off), (0, quantity - move_qty, stay_off)):
            amount = per * qty
            gross[part] += amount
            line_off[part] += off
            bears_vat, bears_service = bearing[item["item_id"]]
            if bears_service:
                service_weight[part] += amount - off
            if bears_vat:
                vat_weight[part] += amount - off
        if move_qty:
            moves.append((item, move_qty, move_off, stay_off))

    if sum(gross) != order["subtotal_cents"]:
        raise SplitError("ยอดรายการในบิลไม่ตรงกับยอดบิล แยกบิลไม่ได้", 409)
    bill_off = order["discount_cents"] - sum(line_off)
    if bill_off < 0:
        raise SplitError("ส่วนลดในบิลนี้ไม่สมเหตุสมผล แยกบิลไม่ได้", 409)
    net = [gross[part] - line_off[part] for part in (0, 1)]
    bill_shares = _share(net, bill_off)
    service_shares = _share(service_weight, order["service_charge_cents"])
    vat_shares = _share(vat_weight, order["vat_cents"])

    money = []
    for part in (0, 1):
        discount = line_off[part] + bill_shares[part]
        money.append({"subtotal_cents": gross[part], "discount_cents": discount,
                      "service_charge_cents": service_shares[part],
                      "vat_cents": vat_shares[part],
                      "total_cents": gross[part] - discount + service_shares[part] + vat_shares[part]})
    # ผลรวมต้องเท่าใบเดิมทุกสตางค์ ถ้าไม่เท่าคือคิดผิด ห้ามเขียนลงฐานข้อมูล
    if sum(part["total_cents"] for part in money) != order["total_cents"]:
        raise SplitError("แบ่งยอดบิลนี้ไม่ลงตัว ยังไม่แยกให้", 409)

    return money[0], money[1], moves


def split_order(conn: sqlite3.Connection, *, order_no: str, branch_id: int,
                picks: dict[int, int], new_order_no: str, event_id: str,
                staff: dict | None) -> dict:
    """ย้ายจำนวนที่เลือกของบางรายการออกไปเป็นบิลใหม่บนโต๊ะเดิม

    ``picks`` คือ {rowid ของรายการ: จำนวนที่ย้ายออก} — ย้ายได้ทีละบางส่วนของรายการ
    เพราะ "ข้าวผัด 3 จาน" บนโต๊ะเดียวคือคนละคนจ่าย

    ย้ายออกทั้งบิลไม่ได้: นั่นคือการย้ายโต๊ะหรือเปลี่ยนเลขบิล ไม่ใช่การแยก
    """
    if not new_order_no or len(new_order_no) > 60 or not event_id or len(event_id) > 80:
        raise SplitError("เลขบิลใหม่หรือรหัสรายการไม่ถูกต้อง")
    done = conn.execute("SELECT order_no FROM order_events WHERE event_id=?", (event_id,)).fetchone()
    if done:
        # กดซ้ำเพราะเน็ตช้า ไม่ใช่ขอแยกอีกครั้ง
        return {"status": "existing", "new_order_no": done[0]}
    if conn.execute("SELECT 1 FROM order_events WHERE order_no=?", (new_order_no,)).fetchone():
        raise SplitError("เลขบิลใหม่นี้มีอยู่แล้ว", 409)

    order = order_of(conn, order_no, branch_id)
    items = items_of(conn, order_no)
    by_line = {item["line_id"]: item for item in items}
    if not picks:
        raise SplitError("ยังไม่ได้เลือกรายการที่จะแยกออก")
    moved_any = 0
    for line_id, qty in picks.items():
        item = by_line.get(int(line_id))
        if item is None:
            raise SplitError("รายการที่เลือกไม่อยู่ในบิลนี้", 409)
        qty = int(qty)
        if qty < 1 or qty > int(item["quantity"]):
            raise SplitError(f"จำนวนที่แยกของ {item['name']} ไม่ถูกต้อง")
        moved_any += qty
    if moved_any >= sum(int(item["quantity"]) for item in items):
        raise SplitError("แยกออกทั้งบิลไม่ได้ ถ้าจะเปลี่ยนโต๊ะให้ใช้ย้ายโต๊ะ")

    kept, created, moves = parts_of(conn, order, items, picks)
    money = [kept, created]

    for item, move_qty, move_off, stay_off in moves:
        stay_qty = int(item["quantity"]) - move_qty
        if stay_qty:
            conn.execute("UPDATE order_items SET quantity=?,discount_cents=? WHERE rowid=?",
                         (stay_qty, stay_off, item["line_id"]))
        else:
            conn.execute("DELETE FROM order_items WHERE rowid=?", (item["line_id"],))
        conn.execute("INSERT INTO order_items (order_no,item_id,name,quantity,unit_price,bom_json,"
                     "station,course_mode,options,unit_cost,discount_cents)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (new_order_no, item["item_id"], item["name"], move_qty, item["unit_price"],
                      item["bom_json"], item["station"], item["course_mode"], item["options"],
                      item["unit_cost"], move_off))

    conn.execute("INSERT INTO order_events (event_id,order_no,branch_id,table_no,total_amount,"
                 "note,queue_no,ordered_by,customer_id,subtotal_cents,discount_cents,"
                 "service_charge_cents,vat_cents,discount_reason)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (event_id, new_order_no, branch_id, order["table_no"],
                  money[1]["total_cents"] / 100, order["note"], _queue_no(conn, branch_id),
                  order["ordered_by"], order["customer_id"], money[1]["subtotal_cents"],
                  money[1]["discount_cents"], money[1]["service_charge_cents"],
                  money[1]["vat_cents"], order["discount_reason"]))
    _write_totals(conn, order_no, money[0])

    # ครัวทำอาหารจานเดิม เพียงแต่อยู่ใต้เลขบิลใหม่ จึงคัดลอกสถานะตั๋วตามไป
    # ไม่สร้างตั๋วใหม่แบบ queued เพราะของที่เสิร์ฟแล้วจะขึ้นจอครัวซ้ำ
    tickets = _ticket_rows(conn, order_no)
    stations_left = {row[0] for row in conn.execute(
        "SELECT DISTINCT station FROM order_items WHERE order_no=?", (order_no,))}
    for station in {item["station"] for item, *_ in moves}:
        row = tickets.get(station)
        if row is None:
            conn.execute("INSERT OR IGNORE INTO kds_station_tickets(order_no,station,status)"
                         " VALUES (?,?,'queued')", (new_order_no, station))
            continue
        conn.execute("INSERT OR IGNORE INTO kds_station_tickets"
                     "(order_no,station,status,created_at,fired_at,ready_at) VALUES (?,?,?,?,?,?)",
                     (new_order_no, station, row[1], row[2], row[3], row[4]))
    for station in set(tickets) - stations_left:
        conn.execute("DELETE FROM kds_station_tickets WHERE order_no=? AND station=?",
                     (order_no, station))

    activity.record(conn, branch_id=branch_id, staff=staff, action="split_bill",
                    subject=f"บิล {order_no} → {new_order_no}",
                    detail=f"โต๊ะ {order['table_no']} · แยกออก {moved_any} รายการ",
                    amount_cents=money[1]["total_cents"])
    return {"status": "split", "table_no": order["table_no"],
            "kept": _summary(order_no, order["table_no"], money[0]),
            "created": _summary(new_order_no, order["table_no"], money[1])}


def move_order(conn: sqlite3.Connection, *, order_no: str, branch_id: int,
               table_no: str, staff: dict | None) -> dict:
    """ย้ายบิลที่ยังไม่จ่ายไปอีกโต๊ะ

    ลูกค้าย้ายโต๊ะเพราะแดด เพราะเสียงดัง เพราะมากันเพิ่ม ของเดิมต้องยกเลิกบิลแล้ว
    คีย์ใหม่ ซึ่งทำให้ยอดยกเลิกของวันโตขึ้นเรื่อย ๆ โดยไม่มีใครโกงอะไรเลย
    """
    table_no = " ".join(str(table_no or "").split())
    if not table_no or len(table_no) > 24:
        raise SplitError("เลขโต๊ะไม่ถูกต้อง")
    order = order_of(conn, order_no, branch_id)
    if order["table_no"] == table_no:
        raise SplitError("บิลนี้อยู่โต๊ะนี้แล้ว", 409)
    seat = conn.execute("SELECT active FROM shop_tables WHERE branch_id=? AND table_no=?",
                        (branch_id, table_no)).fetchone()
    if seat is None:
        raise SplitError(f"ไม่มีโต๊ะ {table_no} ในสาขานี้", 404)
    if not seat[0]:
        raise SplitError(f"โต๊ะ {table_no} ถูกปิดใช้งานอยู่", 409)
    conn.execute("UPDATE order_events SET table_no=? WHERE order_no=?", (table_no, order_no))
    activity.record(conn, branch_id=branch_id, staff=staff, action="move_table",
                    subject=f"บิล {order_no}",
                    detail=f"โต๊ะ {order['table_no']} → โต๊ะ {table_no}",
                    amount_cents=order["total_cents"])
    return {"status": "moved", "order_no": order_no, "from_table": order["table_no"],
            "table_no": table_no}


def merge_orders(conn: sqlite3.Connection, *, order_no: str, into_order_no: str,
                 branch_id: int, staff: dict | None) -> dict:
    """รวมบิลหนึ่งเข้าอีกบิล ให้จ่ายใบเดียว

    บิลต้นทางเหลือไว้เป็นประวัติในสถานะ ``merged`` และยอดถูกตั้งเป็นศูนย์ เพราะ
    ถ้าปล่อยยอดไว้ รายงานไหนที่บวกบิลที่ยังเปิดอยู่จะนับเงินก้อนเดียวสองครั้ง
    """
    if order_no == into_order_no:
        raise SplitError("รวมบิลเข้าตัวเองไม่ได้")
    source = order_of(conn, order_no, branch_id)
    target = order_of(conn, into_order_no, branch_id)
    items = items_of(conn, order_no)
    items_of(conn, into_order_no)   # ปลายทางต้องเป็นบิลจริงที่มีของ ไม่ใช่บิลเปล่า

    money = {field: source[field] + target[field] for field in
             ("subtotal_cents", "discount_cents", "service_charge_cents", "vat_cents")}
    money["total_cents"] = source["total_cents"] + target["total_cents"]

    conn.execute("UPDATE order_items SET order_no=? WHERE order_no=?", (into_order_no, order_no))
    # ตั๋วครัว: สถานีที่มีอยู่ทั้งสองใบเก็บตั๋วของใบปลายทาง แต่ถอยสถานะกลับไปที่
    # "ทำน้อยที่สุด" ของสองใบ ไม่งั้นอาหารที่ยังไม่ได้ทำจะหายจากจอครัว
    here = _ticket_rows(conn, into_order_no)
    for station, row in _ticket_rows(conn, order_no).items():
        if station not in here:
            conn.execute("UPDATE kds_station_tickets SET order_no=? WHERE order_no=? AND station=?",
                         (into_order_no, order_no, station))
            continue
        if TICKET_ORDER.get(row[1], 1) < TICKET_ORDER.get(here[station][1], 1):
            conn.execute("UPDATE kds_station_tickets SET status=?,ready_at=NULL"
                         " WHERE order_no=? AND station=?", (row[1], into_order_no, station))
        conn.execute("DELETE FROM kds_station_tickets WHERE order_no=? AND station=?",
                     (order_no, station))

    _write_totals(conn, into_order_no, money)
    conn.execute("UPDATE order_events SET status='merged',total_amount=0,subtotal_cents=0,"
                 "discount_cents=0,service_charge_cents=0,vat_cents=0 WHERE order_no=?",
                 (order_no,))
    activity.record(conn, branch_id=branch_id, staff=staff, action="merge_bill",
                    subject=f"บิล {order_no} → {into_order_no}",
                    detail=f"โต๊ะ {source['table_no']} → โต๊ะ {target['table_no']} · "
                           f"{len(items)} รายการ",
                    amount_cents=source["total_cents"])
    return {"status": "merged", "merged": order_no,
            "into": _summary(into_order_no, target["table_no"], money)}


def table_board(conn: sqlite3.Connection, branch_id: int) -> dict:
    """โต๊ะที่มีบิลค้างอยู่ตอนนี้ สำหรับหน้าจอแยก/ย้าย/รวมบิล

    หน้าจอต้องรู้ทั้งโต๊ะที่ว่าง (ย้ายไปได้) และบิลที่เปิดอยู่ของแต่ละโต๊ะ (รวมได้)
    """
    tables = [{"table_no": row[0], "active": bool(row[1]), "seats": row[2]}
              for row in conn.execute("SELECT table_no,active,seats FROM shop_tables"
                                      " WHERE branch_id=? ORDER BY table_no", (branch_id,))]
    open_bills: dict[str, list] = {}
    for row in conn.execute("SELECT order_no,table_no,total_amount FROM order_events"
                            " WHERE branch_id=? AND status='open' ORDER BY created_at",
                            (branch_id,)):
        open_bills.setdefault(row[1], []).append({"order_no": row[0], "total_amount": row[2]})
    return {"branch_id": branch_id, "tables": tables, "open_bills": open_bills}
