"""A queue of receipts waiting for the machine the printer is plugged into.

The till may be an iPhone, and an iPhone cannot drive a USB or Bluetooth
receipt printer at all: Safari has no Web Bluetooth and the cheap 58mm
printers have no AirPrint. So the phone does not print. It leaves the receipt
here, and a small program running on whatever machine the printer IS plugged
into collects it and prints it. Any device in the shop can then print to the
one printer, including the ones that could never talk to it directly.

The agent proves itself with a key the shop generates, kept hashed here the
way a staff PIN is. A job it takes is leased rather than deleted, so a printer
that jams or a laptop that sleeps mid-job does not silently swallow a bill.

The caller owns the SQLite transaction and has already checked the staff role.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time

# Long enough that guessing is hopeless, short enough to retype from a note.
AGENT_KEY_BYTES = 24
# A job an agent took but never finished goes back in the queue after this.
# A receipt reprinted once is a nuisance; a receipt silently lost is a dispute
# with a customer who is still standing at the counter.
LEASE_SECONDS = 90
MAX_BODY_CHARS = 8000
KEEP_PRINTED = 200


class PrintError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def init_printing(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS print_agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch_id INTEGER NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        key_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS print_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch_id INTEGER NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL,
        copies INTEGER NOT NULL DEFAULT 1 CHECK(copies BETWEEN 1 AND 5),
        status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','taken','printed')),
        taken_at INTEGER,
        agent_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        printed_at TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS print_jobs_waiting ON print_jobs(branch_id,status,id)")


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _branch(value: object) -> int:
    if isinstance(value, bool):
        raise PrintError("สาขาไม่ถูกต้อง")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise PrintError("สาขาไม่ถูกต้อง") from None
    if result < 1:
        raise PrintError("สาขาไม่ถูกต้อง")
    return result


def issue_agent(conn: sqlite3.Connection, branch_id: int, name: str = "") -> dict:
    """Hand out one key. It is shown once, here, and never again.

    A shop with a key it cannot find issues another and deletes the old one;
    that is cheaper for everyone than keeping the key readable on the server.
    """
    branch_id = _branch(branch_id)
    key = secrets.token_urlsafe(AGENT_KEY_BYTES)
    cur = conn.execute("INSERT INTO print_agents(branch_id,name,key_hash) VALUES(?,?,?)",
                       (branch_id, str(name or "").strip()[:60], _hash_key(key)))
    return {"id": cur.lastrowid, "name": str(name or "").strip()[:60], "key": key}


def list_agents(conn: sqlite3.Connection, branch_id: int) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id,name,created_at,last_seen_at FROM print_agents"
                        " WHERE branch_id=? ORDER BY id", (_branch(branch_id),)).fetchall()
    return [dict(row) for row in rows]


def delete_agent(conn: sqlite3.Connection, branch_id: int, agent_id: int) -> None:
    removed = conn.execute("DELETE FROM print_agents WHERE branch_id=? AND id=?",
                           (_branch(branch_id), int(agent_id))).rowcount
    if not removed:
        raise PrintError("ไม่พบเครื่องพิมพ์นี้", 404)


def agent_for_key(conn: sqlite3.Connection, key: str) -> dict:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id,branch_id,name FROM print_agents WHERE key_hash=?",
                       (_hash_key(str(key or "")),)).fetchone()
    if not row:
        raise PrintError("กุญแจเครื่องพิมพ์ไม่ถูกต้อง", 401)
    conn.execute("UPDATE print_agents SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
    return dict(row)


def queue_job(conn: sqlite3.Connection, branch_id: int, title: str, body: str,
              copies: int = 1) -> dict:
    branch_id = _branch(branch_id)
    text = str(body or "").strip()
    if not text:
        raise PrintError("ไม่มีอะไรให้พิมพ์")
    if len(text) > MAX_BODY_CHARS:
        raise PrintError("ใบเสร็จยาวเกินไป")
    if not conn.execute("SELECT 1 FROM print_agents WHERE branch_id=?", (branch_id,)).fetchone():
        raise PrintError("ยังไม่ได้ตั้งค่าเครื่องพิมพ์ของร้านนี้", 409)
    try:
        copies = max(1, min(5, int(copies)))
    except (TypeError, ValueError):
        copies = 1
    cur = conn.execute("INSERT INTO print_jobs(branch_id,title,body,copies) VALUES(?,?,?,?)",
                       (branch_id, str(title or "")[:80], text, copies))
    return {"job_id": cur.lastrowid, "queued": waiting_count(conn, branch_id)}


def waiting_count(conn: sqlite3.Connection, branch_id: int) -> int:
    row = conn.execute("SELECT COUNT(*) FROM print_jobs WHERE branch_id=? AND status<>'printed'",
                       (_branch(branch_id),)).fetchone()
    return int(row[0])


def take_job(conn: sqlite3.Connection, agent: dict) -> dict | None:
    """The next receipt for this agent's branch, oldest first."""
    conn.row_factory = sqlite3.Row
    now = int(time.time())
    # Anything a previous run took and never finished is fair game again.
    conn.execute("UPDATE print_jobs SET status='queued',taken_at=NULL,agent_id=NULL"
                 " WHERE status='taken' AND taken_at<?", (now - LEASE_SECONDS,))
    row = conn.execute("SELECT id,title,body,copies FROM print_jobs"
                       " WHERE branch_id=? AND status='queued' ORDER BY id LIMIT 1",
                       (agent["branch_id"],)).fetchone()
    if not row:
        return None
    conn.execute("UPDATE print_jobs SET status='taken',taken_at=?,agent_id=? WHERE id=?",
                 (now, agent["id"], row["id"]))
    return {"job_id": row["id"], "title": row["title"], "body": row["body"],
            "copies": row["copies"]}


def finish_job(conn: sqlite3.Connection, agent: dict, job_id: int) -> None:
    done = conn.execute("UPDATE print_jobs SET status='printed',printed_at=CURRENT_TIMESTAMP"
                        " WHERE id=? AND branch_id=? AND status<>'printed'",
                        (int(job_id), agent["branch_id"])).rowcount
    if not done:
        raise PrintError("ไม่พบงานพิมพ์นี้", 404)
    # Keep the last few for "did that bill print?", and no more than that.
    conn.execute("DELETE FROM print_jobs WHERE branch_id=? AND status='printed' AND id NOT IN ("
                 "SELECT id FROM print_jobs WHERE branch_id=? AND status='printed'"
                 " ORDER BY id DESC LIMIT ?)",
                 (agent["branch_id"], agent["branch_id"], KEEP_PRINTED))
