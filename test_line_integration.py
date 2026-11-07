import base64
import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_integration as line
import line_pos_server as server


def _signature(body: bytes, secret: str) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def test_line_signature_uses_raw_body():
    body = b'{"events":[]}'
    line.verify_webhook_signature(body, _signature(body, "secret"), "secret")
    try:
        line.verify_webhook_signature(body + b" ", _signature(body, "secret"), "secret")
    except Exception as exc:
        assert exc.status_code == 401
    else:
        assert False, "Modified body must be rejected"


def test_liff_token_rejects_wrong_channel_and_expiration():
    class Response:
        def __init__(self, claims):
            self.claims = claims

        def raise_for_status(self):
            pass

        def json(self):
            return self.claims

    with patch.object(line.httpx, "post", return_value=Response({"aud": "123", "sub": "Ustaff", "exp": time.time() + 60})):
        assert line.verify_liff_id_token("token", "123") == "Ustaff"
    for claims in ({"aud": "other", "sub": "Ustaff", "exp": time.time() + 60},
                   {"aud": "123", "sub": "Ustaff", "exp": time.time() - 1}):
        with patch.object(line.httpx, "post", return_value=Response(claims)):
            try:
                line.verify_liff_id_token("token", "123")
            except Exception as exc:
                assert exc.status_code == 401
            else:
                assert False, "Invalid token claims must fail"


def test_leave_requires_linked_line_identity_and_manager_signature():
    with TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        database = Path(folder) / "line-test.db"
        with patch.object(server, "DB_PATH", database), patch.object(server, "PREVIEW_ONLY", False), \
             patch.object(server, "LINE_LOGIN_CHANNEL_ID", "123"), \
             patch.object(server, "LINE_CHANNEL_SECRET", "secret"), \
             patch.object(server, "LINE_CHANNEL_ACCESS_TOKEN", ""):
            server.init_db()
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("INSERT INTO branches (id,name) VALUES (1,'Test')")
                conn.execute("INSERT INTO staffs (id,branch_id,line_user_id,name,role,pin_code_hash) VALUES (1,1,'Ustaff','Staff','cashier','x')")
                conn.execute("INSERT INTO staffs (id,branch_id,line_user_id,name,role,pin_code_hash) VALUES (2,1,'Umanager','Manager','manager','x')")
                conn.commit()
            client = TestClient(server.app)
            payload = {"event_id": "leave-1", "staff_id": 1, "leave_type": "sick",
                       "start_date": "2026-10-20", "end_date": "2026-10-21", "reason": "ill", "line_id_token": "token"}
            with patch.object(server, "verify_liff_id_token", return_value="Uother"):
                assert client.post("/api/line-liff/leave-requests", json=payload).status_code == 403
            with patch.object(server, "verify_liff_id_token", return_value="Ustaff"):
                response = client.post("/api/line-liff/leave-requests", json=payload)
            assert response.status_code == 200
            leave_id = response.json()["leave_id"]
            assert response.json()["line_flex_notification"] == "not_configured"
            event = {"events": [{"type": "postback", "source": {"userId": "Ustaff"},
                                  "postback": {"data": f"action=review_leave&leave_id={leave_id}&decision=approved"}}]}
            body = json.dumps(event).encode()
            assert client.post("/api/line-webhook", content=body).status_code == 401
            assert client.post("/api/line-webhook", content=body, headers={"x-line-signature": "bad"}).status_code == 401
            assert client.post("/api/line-webhook", content=body, headers={"x-line-signature": _signature(body, "secret")}).json()["reviewed"] == []
            event["events"][0]["source"]["userId"] = "Umanager"
            body = json.dumps(event).encode()
            result = client.post("/api/line-webhook", content=body, headers={"x-line-signature": _signature(body, "secret")})
            assert result.status_code == 200
            assert result.json()["reviewed"][0]["status"] == "approved"
            with closing(sqlite3.connect(database)) as conn:
                dates = conn.execute("SELECT work_date FROM staff_shifts WHERE staff_id=1 AND pos_pin_locked=1 ORDER BY work_date").fetchall()
                assert dates == [("2026-10-20",), ("2026-10-21",)]
