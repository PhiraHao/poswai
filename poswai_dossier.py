"""Staff dossier: employment facts, hiring documents, store assets and history.

Restaurants are inspected on paperwork the owner cannot produce from memory —
food handler cards, annual medical certificates, work permits — so this module
tracks what each person has handed in and when it expires. It stores facts about
documents, never the documents themselves.
"""

import datetime
import sqlite3

# Every document a Thai restaurant is normally asked for. `expires` marks the
# ones an inspector will check the date on.
DOCUMENT_TYPES = (
    {"key": "id_card", "label": "สำเนาบัตรประชาชน / พาสปอร์ต", "expires": False},
    {"key": "work_permit", "label": "ใบอนุญาตทำงาน (แรงงานต่างด้าว)", "expires": True, "optional": True},
    {"key": "house_registration", "label": "สำเนาทะเบียนบ้าน", "expires": False},
    {"key": "bank_book", "label": "หน้าสมุดบัญชีธนาคาร", "expires": False},
    {"key": "contract", "label": "สัญญาจ้างงาน", "expires": False},
    {"key": "medical_certificate", "label": "ใบรับรองแพทย์ตรวจโรคติดต่อ", "expires": True},
    {"key": "food_handler", "label": "บัตรผ่านการอบรมผู้สัมผัสอาหาร", "expires": True},
)
DOCUMENT_KEYS = {doc["key"] for doc in DOCUMENT_TYPES}
EMPLOYMENT_TYPES = {"full_time": "พนักงานประจำ", "part_time": "พาร์ทไทม์",
                    "probation": "ทดลองงาน", "daily": "รายวัน"}
TIMELINE_KINDS = {"milestone": "เหตุการณ์", "pay_change": "ปรับค่าแรง",
                  "warning": "ใบเตือน", "note": "บันทึก"}
EXPIRY_WARNING_DAYS = 30
PROBATION_WARNING_DAYS = 14
TEXT_FIELDS = ("nickname", "phone", "line_display", "bank_name", "bank_account",
               "emergency_contact", "emergency_phone", "medical_note")
DATE_FIELDS = ("start_date", "probation_end_date")


class DossierError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init_dossier(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS staff_profiles (
        staff_id INTEGER PRIMARY KEY REFERENCES staffs(id),
        nickname TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        line_display TEXT NOT NULL DEFAULT '',
        start_date TEXT,
        employment_type TEXT NOT NULL DEFAULT 'full_time',
        probation_end_date TEXT,
        bank_name TEXT NOT NULL DEFAULT '',
        bank_account TEXT NOT NULL DEFAULT '',
        emergency_contact TEXT NOT NULL DEFAULT '',
        emergency_phone TEXT NOT NULL DEFAULT '',
        medical_note TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS staff_documents (
        staff_id INTEGER NOT NULL REFERENCES staffs(id),
        doc_type TEXT NOT NULL,
        received INTEGER NOT NULL DEFAULT 0,
        expires_on TEXT,
        note TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES staffs(id),
        PRIMARY KEY (staff_id, doc_type))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS staff_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL REFERENCES staffs(id),
        item TEXT NOT NULL,
        issued_on TEXT NOT NULL,
        returned_on TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS staff_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL REFERENCES staffs(id),
        event_date TEXT NOT NULL,
        kind TEXT NOT NULL,
        detail TEXT NOT NULL,
        created_by INTEGER REFERENCES staffs(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("CREATE INDEX IF NOT EXISTS staff_timeline_by_staff "
                 "ON staff_timeline(staff_id,event_date DESC,id DESC)")


def _date(value: str | None, field: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise DossierError(f"{field} must be a YYYY-MM-DD date") from exc


def tenure(start_date: str | None, today: datetime.date) -> dict:
    """Months of service, in the words a roster conversation uses."""
    if not start_date:
        return {"text": "ยังไม่ได้บันทึกวันเริ่มงาน", "months": None, "started": None}
    start = datetime.date.fromisoformat(start_date)
    if start > today:
        return {"text": f"เริ่มงาน {start_date}", "months": 0, "started": start_date}
    months = (today.year - start.year) * 12 + today.month - start.month
    if today.day < start.day:
        months -= 1
    months = max(months, 0)
    years, rest = divmod(months, 12)
    parts = ([f"{years} ปี"] if years else []) + ([f"{rest} เดือน"] if rest else [])
    return {"text": " ".join(parts) or "น้อยกว่า 1 เดือน", "months": months, "started": start_date}


def _probation(row: sqlite3.Row, today: datetime.date) -> dict:
    if row["employment_type"] != "probation":
        return {"on_probation": False, "ends_on": row["probation_end_date"],
                "days_left": None, "status": "ผ่านทดลองงานแล้ว"}
    ends_on = row["probation_end_date"]
    if not ends_on:
        return {"on_probation": True, "ends_on": None, "days_left": None,
                "status": "ทดลองงาน · ยังไม่ได้กำหนดวันครบกำหนด"}
    days_left = (datetime.date.fromisoformat(ends_on) - today).days
    if days_left < 0:
        status = f"ครบกำหนดประเมินแล้ว {abs(days_left)} วัน"
    elif days_left <= PROBATION_WARNING_DAYS:
        status = f"ใกล้ครบกำหนดประเมิน อีก {days_left} วัน"
    else:
        status = f"ทดลองงาน เหลืออีก {days_left} วัน"
    return {"on_probation": True, "ends_on": ends_on, "days_left": days_left, "status": status}


def _documents(conn: sqlite3.Connection, staff_id: int, today: datetime.date) -> list[dict]:
    stored = {row["doc_type"]: row for row in conn.execute(
        "SELECT doc_type,received,expires_on,note,updated_at FROM staff_documents WHERE staff_id=?",
        (staff_id,))}
    documents = []
    for doc in DOCUMENT_TYPES:
        row = stored.get(doc["key"])
        received = bool(row["received"]) if row else False
        expires_on = row["expires_on"] if row else None
        days_left = (datetime.date.fromisoformat(expires_on) - today).days if expires_on else None
        # A work permit only applies to foreign staff, so an empty one is not a gap.
        state = "received" if received else ("optional" if doc.get("optional") else "missing")
        if received and days_left is not None:
            if days_left < 0:
                state = "expired"
            elif days_left <= EXPIRY_WARNING_DAYS:
                state = "expiring"
        documents.append({"optional": False, **doc, "received": received, "expires_on": expires_on,
                          "days_left": days_left, "state": state,
                          "note": row["note"] if row else "",
                          "updated_at": row["updated_at"] if row else None})
    return documents


def read_dossier(conn: sqlite3.Connection, staff_id: int, today: datetime.date) -> dict:
    conn.row_factory = sqlite3.Row
    staff = conn.execute("SELECT id,name,role,branch_id,hourly_rate,is_active,line_user_id "
                         "FROM staffs WHERE id=?", (staff_id,)).fetchone()
    if not staff:
        raise DossierError("Staff not found", 404)
    row = conn.execute("SELECT * FROM staff_profiles WHERE staff_id=?", (staff_id,)).fetchone()
    if not row:
        conn.execute("INSERT OR IGNORE INTO staff_profiles (staff_id) VALUES (?)", (staff_id,))
        row = conn.execute("SELECT * FROM staff_profiles WHERE staff_id=?", (staff_id,)).fetchone()
    documents = _documents(conn, staff_id, today)
    assets = [dict(item) for item in conn.execute(
        "SELECT id,item,issued_on,returned_on FROM staff_assets WHERE staff_id=? "
        "ORDER BY returned_on IS NOT NULL,id DESC", (staff_id,))]
    timeline = [dict(item) for item in conn.execute(
        "SELECT id,event_date,kind,detail FROM staff_timeline WHERE staff_id=? "
        "ORDER BY event_date DESC,id DESC LIMIT 100", (staff_id,))]
    profile = {field: row[field] for field in (*TEXT_FIELDS, *DATE_FIELDS, "employment_type")}
    return {
        "staff": {"id": staff["id"], "name": staff["name"], "role": staff["role"],
                  "branch_id": staff["branch_id"], "hourly_rate": staff["hourly_rate"],
                  "is_active": bool(staff["is_active"]), "line_linked": bool(staff["line_user_id"])},
        "profile": profile,
        "employment_label": EMPLOYMENT_TYPES.get(row["employment_type"], row["employment_type"]),
        "tenure": tenure(row["start_date"], today),
        "probation": _probation(row, today),
        "documents": documents,
        "documents_missing": [doc["label"] for doc in documents if doc["state"] == "missing"],
        "documents_attention": [doc["label"] for doc in documents if doc["state"] in ("expired", "expiring")],
        "assets": assets,
        "assets_outstanding": sum(1 for item in assets if not item["returned_on"]),
        "timeline": [{**item, "kind_label": TIMELINE_KINDS.get(item["kind"], item["kind"])}
                     for item in timeline],
        "updated_at": row["updated_at"],
    }


def update_profile(conn: sqlite3.Connection, staff_id: int, fields: dict) -> None:
    updates = {}
    for field, value in fields.items():
        if value is None:
            continue
        if field in TEXT_FIELDS:
            text = str(value).strip()
            limit = 300 if field == "medical_note" else 120
            if len(text) > limit:
                raise DossierError(f"{field} is longer than {limit} characters")
            updates[field] = text
        elif field in DATE_FIELDS:
            updates[field] = _date(str(value), field)
        elif field == "employment_type":
            if value not in EMPLOYMENT_TYPES:
                raise DossierError("Unknown employment type")
            updates[field] = value
        else:
            raise DossierError(f"Unknown profile field: {field}")
    if not updates:
        raise DossierError("No dossier changes supplied")
    conn.execute("INSERT OR IGNORE INTO staff_profiles (staff_id) VALUES (?)", (staff_id,))
    assignments = ",".join(f"{field}=?" for field in updates)
    conn.execute(f"UPDATE staff_profiles SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE staff_id=?",
                 (*updates.values(), staff_id))


def set_document(conn: sqlite3.Connection, staff_id: int, doc_type: str, received: bool,
                 expires_on: str | None, note: str, actor_id: int) -> None:
    if doc_type not in DOCUMENT_KEYS:
        raise DossierError("Unknown document type", 404)
    if len(note or "") > 200:
        raise DossierError("Document note is longer than 200 characters")
    conn.execute("INSERT INTO staff_documents (staff_id,doc_type,received,expires_on,note,updated_by) "
                 "VALUES (?,?,?,?,?,?) ON CONFLICT(staff_id,doc_type) DO UPDATE SET "
                 "received=excluded.received,expires_on=excluded.expires_on,note=excluded.note,"
                 "updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP",
                 (staff_id, doc_type, 1 if received else 0, _date(expires_on, "expires_on"),
                  (note or "").strip(), actor_id))


def add_asset(conn: sqlite3.Connection, staff_id: int, item: str, issued_on: str | None,
              today: datetime.date) -> int:
    name = (item or "").strip()
    if not 1 <= len(name) <= 80:
        raise DossierError("Asset name must be 1 to 80 characters")
    cursor = conn.execute("INSERT INTO staff_assets (staff_id,item,issued_on) VALUES (?,?,?)",
                          (staff_id, name, _date(issued_on, "issued_on") or today.isoformat()))
    return cursor.lastrowid


def return_asset(conn: sqlite3.Connection, staff_id: int, asset_id: int, returned: bool,
                 today: datetime.date) -> None:
    changed = conn.execute("UPDATE staff_assets SET returned_on=? WHERE id=? AND staff_id=?",
                           (today.isoformat() if returned else None, asset_id, staff_id))
    if not changed.rowcount:
        raise DossierError("Asset not found", 404)


def add_timeline_entry(conn: sqlite3.Connection, staff_id: int, event_date: str | None, kind: str,
                       detail: str, actor_id: int, today: datetime.date) -> int:
    if kind not in TIMELINE_KINDS:
        raise DossierError("Unknown timeline entry type")
    text = (detail or "").strip()
    if not 1 <= len(text) <= 300:
        raise DossierError("Timeline detail must be 1 to 300 characters")
    cursor = conn.execute(
        "INSERT INTO staff_timeline (staff_id,event_date,kind,detail,created_by) VALUES (?,?,?,?,?)",
        (staff_id, _date(event_date, "event_date") or today.isoformat(), kind, text, actor_id))
    return cursor.lastrowid


def branch_summary(conn: sqlite3.Connection, branch_id: int, today: datetime.date) -> list[dict]:
    """One line per active person: what is missing and what is about to expire."""
    conn.row_factory = sqlite3.Row
    people = conn.execute("SELECT id,name,role FROM staffs WHERE branch_id=? AND is_active=1 ORDER BY id",
                          (branch_id,)).fetchall()
    summary = []
    for person in people:
        row = conn.execute("SELECT * FROM staff_profiles WHERE staff_id=?", (person["id"],)).fetchone()
        documents = _documents(conn, person["id"], today)
        probation = _probation(row, today) if row else {"on_probation": False, "days_left": None,
                                                        "status": "ผ่านทดลองงานแล้ว", "ends_on": None}
        summary.append({
            "id": person["id"], "name": person["name"], "role": person["role"],
            "tenure": tenure(row["start_date"] if row else None, today)["text"],
            "missing": sum(1 for doc in documents if doc["state"] == "missing"),
            "attention": sum(1 for doc in documents if doc["state"] in ("expired", "expiring")),
            "probation": probation,
            "assets_outstanding": conn.execute(
                "SELECT COUNT(*) FROM staff_assets WHERE staff_id=? AND returned_on IS NULL",
                (person["id"],)).fetchone()[0],
        })
    return summary
