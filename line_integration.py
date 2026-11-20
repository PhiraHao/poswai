"""Small LINE API boundary. Never trust LINE profile data sent by a browser."""

import base64
import hashlib
import hmac
import time
from urllib.parse import parse_qs

import httpx
from fastapi import HTTPException


LINE_API = "https://api.line.me"


def verify_liff_id_token(id_token: str, channel_id: str) -> str:
    """Return the verified LINE user ID, bound to our LINE Login channel."""
    if not channel_id or not id_token:
        raise HTTPException(status_code=503 if not channel_id else 401, detail="LINE LIFF identity is unavailable")
    try:
        response = httpx.post(
            f"{LINE_API}/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": channel_id},
            timeout=8,
        )
        response.raise_for_status()
        profile = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired LINE ID token") from exc
    if profile.get("aud") != channel_id or not profile.get("sub") or profile.get("exp", 0) <= time.time():
        raise HTTPException(status_code=401, detail="Invalid LINE ID token claims")
    return profile["sub"]


def verify_webhook_signature(body: bytes, signature: str | None, channel_secret: str) -> None:
    if not channel_secret:
        raise HTTPException(status_code=503, detail="LINE Messaging channel is not configured")
    expected = base64.b64encode(hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()).decode()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid LINE webhook signature")


def parse_leave_postback(value: str) -> tuple[int, str] | None:
    if len(value) > 120:
        return None
    data = parse_qs(value, strict_parsing=False)
    if data.get("action") != ["review_leave"] or data.get("decision") not in (["approved"], ["rejected"]):
        return None
    try:
        leave_id = int(data.get("leave_id", [""])[0])
    except ValueError:
        return None
    if leave_id <= 0:
        return None
    return leave_id, data["decision"][0]


def build_leave_flex(leave_id: int, staff_name: str, leave_type: str, start_date: str, end_date: str, reason: str) -> dict:
    # LINE Flex text limits are enforced here so user text cannot invalidate a push.
    details = f"{staff_name[:80]} · {leave_type[:30]}\n{start_date} ถึง {end_date}\n{reason[:400]}"
    return {
        "type": "flex",
        "altText": f"คำขอลา #{leave_id} รออนุมัติ",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": "คำขอลาพนักงาน", "weight": "bold", "size": "lg"},
                {"type": "text", "text": details, "wrap": True, "margin": "md"},
            ]},
            "footer": {"type": "box", "layout": "horizontal", "contents": [
                {"type": "button", "style": "primary", "color": "#0B805C", "action": {
                    "type": "postback", "label": "อนุมัติ", "data": f"action=review_leave&leave_id={leave_id}&decision=approved"}},
                {"type": "button", "style": "secondary", "action": {
                    "type": "postback", "label": "ปฏิเสธ", "data": f"action=review_leave&leave_id={leave_id}&decision=rejected"}},
            ]},
        },
    }


def push_leave_request(access_token: str, manager_line_ids: list[str], message: dict) -> str:
    if not access_token:
        return "not_configured"
    if not manager_line_ids:
        return "no_bound_manager"
    failed = 0
    for manager_id in manager_line_ids:
        try:
            response = httpx.post(
                f"{LINE_API}/v2/bot/message/push",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"to": manager_id, "messages": [message]}, timeout=8,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            failed += 1
    return "sent" if not failed else "delivery_failed"
