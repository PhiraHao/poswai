"""Persist LINE operational pushes so transient failures can be retried."""

import json
import sqlite3
import time
import uuid

import httpx


def init_notifications(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS line_notification_outbox (
        event_key TEXT NOT NULL, recipient TEXT NOT NULL, branch_id INTEGER NOT NULL,
        message_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER NOT NULL DEFAULT 0,
        last_error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        sent_at TEXT, PRIMARY KEY(event_key,recipient))""")


def enqueue(conn: sqlite3.Connection, event_key: str, recipient: str, branch_id: int, message: dict) -> None:
    conn.execute("INSERT OR IGNORE INTO line_notification_outbox "
                 "(event_key,recipient,branch_id,message_json) VALUES (?,?,?,?)",
                 (event_key, recipient, branch_id, json.dumps(message, ensure_ascii=False)))


def flush(conn: sqlite3.Connection, access_token: str, branch_id: int | None = None, limit: int = 20) -> dict:
    if not access_token:
        return {"status": "not_configured", "sent": 0, "failed": 0}
    now = int(time.time())
    where = "status='pending' AND next_attempt_at<=?"
    params: list = [now]
    if branch_id is not None:
        where += " AND branch_id=?"
        params.append(branch_id)
    rows = conn.execute(f"SELECT event_key,recipient,message_json,attempts FROM line_notification_outbox "
                        f"WHERE {where} ORDER BY created_at LIMIT ?", (*params, min(limit, 100))).fetchall()
    sent = failed = 0
    for key, recipient, raw_message, attempts in rows:
        try:
            response = httpx.post("https://api.line.me/v2/bot/message/push",
                                  headers={"Authorization": f"Bearer {access_token}",
                                           "X-Line-Retry-Key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"poswai:{key}:{recipient}"))},
                                  json={"to": recipient, "messages": [json.loads(raw_message)]}, timeout=8)
            if response.status_code != 409:
                response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            attempts += 1
            delay = min(60 * 2 ** min(attempts - 1, 8), 3600)
            conn.execute("UPDATE line_notification_outbox SET attempts=?,next_attempt_at=?,last_error=? "
                         "WHERE event_key=? AND recipient=? AND status='pending'",
                         (attempts, now + delay, type(exc).__name__, key, recipient))
            failed += 1
        else:
            conn.execute("UPDATE line_notification_outbox SET status='sent',attempts=attempts+1," 
                         "sent_at=CURRENT_TIMESTAMP,last_error=NULL WHERE event_key=? AND recipient=?",
                         (key, recipient))
            sent += 1
        conn.commit()
    return {"status": "processed", "sent": sent, "failed": failed}
