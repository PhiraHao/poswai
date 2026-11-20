"""Manager configuration and durable LINE leave notifications."""

import sqlite3
import datetime
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

import line_pos_server as server


def test_manager_shift_rates_and_attendance_idempotency():
    with TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        database = Path(folder) / "staff.db"
        with patch.object(server, "DB_PATH", database), patch.object(server, "PREVIEW_ONLY", False):
            server.init_db()
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("INSERT INTO branches(id,name) VALUES(1,'One'),(2,'Two')")
                for id_, branch, role in ((1, 1, 'manager'), (2, 1, 'staff'), (3, 2, 'staff')):
                    conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(?,?,?,?,?)",
                                 (id_, branch, str(id_), role, server.hash_pin('long-test-pin')))
            with TestClient(server.app) as client:
                assert client.post('/api/auth/login', json={'staff_id': 1, 'pin': 'long-test-pin'}).status_code == 200
                assert client.patch('/api/staff/2/pay-rate', json={'hourly_rate': 95}).status_code == 200
                assert client.patch('/api/staff/3/pay-rate', json={'hourly_rate': 95}).status_code == 404
                shift = client.post('/api/staff/shift-templates', json={'branch_id': 1, 'name': 'Morning',
                    'start_time': '08:00', 'end_time': '17:00'})
                assert shift.status_code == 200, shift.text
                assert client.post('/api/staff/shifts', json={'branch_id': 1, 'staff_id': 2,
                    'work_date': '2026-10-20', 'shift_template_id': shift.json()['id']}).status_code == 200
                assert client.post('/api/staff/shifts', json={'branch_id': 1, 'staff_id': 3,
                    'work_date': '2026-10-20', 'shift_template_id': shift.json()['id']}).status_code == 404
                event = {'event_id': 'clock-1', 'staff_id': 2, 'action': 'clock_in'}
                assert client.post('/api/attendance', json=event).json()['status'] == 'recorded'
                assert client.post('/api/attendance', json=event).json()['status'] == 'already_recorded'
                assert client.post('/api/attendance', json={**event, 'event_id': 'clock-2'}).status_code == 409
                assert client.post('/api/attendance', json={**event, 'event_id': 'clock-3', 'action': 'clock_out'}).status_code == 200
                assert client.post('/api/attendance', json={**event, 'event_id': 'clock-4', 'action': 'clock_out'}).status_code == 409
                today = datetime.datetime.now(server.BANGKOK_TZ).date().isoformat()
                overnight = client.post('/api/staff/shift-templates', json={'branch_id': 1, 'name': 'Early',
                    'start_time': '00:00', 'end_time': '08:00'}).json()['id']
                assert client.post('/api/staff/shifts', json={'branch_id': 1, 'staff_id': 3,
                    'work_date': today, 'shift_template_id': overnight}).status_code == 404
                assert client.post('/api/staff/shifts', json={'branch_id': 1, 'staff_id': 1,
                    'work_date': today, 'shift_template_id': overnight}).status_code == 200
                absent = client.post('/api/staff/absence-check').json()
                assert absent['absent_staff_ids'] == [1]
                assert client.post('/api/staff/absence-check').status_code == 401


def test_leave_line_outbox_retries_without_duplicate():
    with TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        database = Path(folder) / "line.db"
        with patch.object(server, "DB_PATH", database), patch.object(server, "PREVIEW_ONLY", False), \
             patch.object(server, "LINE_LOGIN_CHANNEL_ID", '123'), patch.object(server, "LINE_CHANNEL_ACCESS_TOKEN", 'token'):
            server.init_db()
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("INSERT INTO branches(id,name) VALUES(1,'One')")
                conn.execute("INSERT INTO staffs(id,branch_id,line_user_id,name,role,pin_code_hash) VALUES(1,1,'Ustaff','Staff','staff',?)", (server.hash_pin('long-test-pin'),))
                conn.execute("INSERT INTO staffs(id,branch_id,line_user_id,name,role,pin_code_hash) VALUES(2,1,'Umanager','Manager','manager',?)", (server.hash_pin('long-test-pin'),))
            with TestClient(server.app) as client, patch.object(server, 'verify_liff_id_token', return_value='Ustaff'):
                with patch('line_notifications.httpx.post') as post:
                    post.return_value.status_code = 500
                    post.return_value.raise_for_status.side_effect = __import__('httpx').HTTPStatusError('fail', request=__import__('httpx').Request('POST', 'https://api.line.me'), response=__import__('httpx').Response(500))
                    result = client.post('/api/line-liff/leave-requests', json={'event_id': 'leave-1', 'staff_id': 1,
                        'leave_type': 'sick', 'start_date': '2026-10-20', 'end_date': '2026-10-20',
                        'reason': 'ill', 'line_id_token': 'test'})
                    assert result.status_code == 200, result.text
                with closing(sqlite3.connect(database)) as conn:
                    assert conn.execute("SELECT COUNT(*) FROM line_notification_outbox").fetchone()[0] == 1
                    conn.execute("UPDATE line_notification_outbox SET next_attempt_at=0")
                    conn.commit()
                assert client.post('/api/auth/login', json={'staff_id': 2, 'pin': 'long-test-pin'}).status_code == 200
                with patch('line_notifications.httpx.post') as post:
                    post.return_value.status_code = 200
                    post.return_value.raise_for_status.return_value = None
                    assert client.post('/api/line/notifications/retry').json()['sent'] == 1
                    assert client.post('/api/line/notifications/retry').json()['sent'] == 0
                    assert post.call_count == 1


def test_staff_live_does_not_open_sales_in_preview():
    with TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        database = Path(folder) / 'preview.db'
        with patch.object(server, 'DB_PATH', database), patch.object(server, 'PREVIEW_ONLY', True), \
             patch.object(server, 'STAFF_LIVE', True):
            server.init_db()
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("INSERT INTO branches(id,name) VALUES(1,'One')")
                conn.execute("INSERT INTO staffs(id,branch_id,name,role,pin_code_hash) VALUES(1,1,'Manager','manager',?)",
                             (server.hash_pin('long-test-pin'),))
            with TestClient(server.app) as client:
                assert client.post('/api/auth/login', json={'staff_id': 1, 'pin': 'long-test-pin'}).status_code == 200
                assert client.post('/api/staff/shift-templates', json={'branch_id': 1, 'name': 'Morning',
                    'start_time': '08:00', 'end_time': '17:00'}).status_code == 200
                assert client.post('/api/orders', json={}).status_code == 403
                assert client.post('/api/crm/campaigns', json={}).status_code == 403
                assert client.get('/api/config').json()['staff_live'] is True
