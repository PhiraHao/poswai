"""Strict EasySlip v2 verification for a single Thai bank transfer slip.

The caller must additionally reserve the returned transaction reference in its
own database transaction. Provider duplicate checks alone do not protect two
simultaneous POS requests using the same image.
"""

import base64
import binascii
from decimal import Decimal, InvalidOperation

import httpx


EASYSLIP_VERIFY_URL = "https://api.easyslip.com/v2/verify/bank"
MAX_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class SlipVerificationError(ValueError):
    pass


def _validated_image(image: str) -> str:
    if not isinstance(image, str) or not image.startswith("data:") or ";base64," not in image:
        raise SlipVerificationError("กรุณาแนบรูปสลิป JPEG, PNG, GIF หรือ WebP")
    prefix, content = image.split(",", 1)
    media_type = prefix.removeprefix("data:").removesuffix(";base64").lower()
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise SlipVerificationError("ชนิดไฟล์สลิปไม่รองรับ")
    if len(content) > (MAX_IMAGE_BYTES * 4 // 3 + 8):
        raise SlipVerificationError("รูปสลิปต้องมีขนาดไม่เกิน 4 MB")
    try:
        decoded = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SlipVerificationError("ข้อมูลรูปสลิปไม่ถูกต้อง") from exc
    if not decoded or len(decoded) > MAX_IMAGE_BYTES:
        raise SlipVerificationError("รูปสลิปต้องมีขนาด 1 ไบต์ถึง 4 MB")
    if media_type == "image/png" and not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SlipVerificationError("ไฟล์ PNG ไม่ถูกต้อง")
    if media_type == "image/jpeg" and not decoded.startswith(b"\xff\xd8\xff"):
        raise SlipVerificationError("ไฟล์ JPEG ไม่ถูกต้อง")
    if media_type == "image/webp" and not (decoded[:4] == b"RIFF" and decoded[8:12] == b"WEBP"):
        raise SlipVerificationError("ไฟล์ WebP ไม่ถูกต้อง")
    if media_type == "image/gif" and decoded[:6] not in (b"GIF87a", b"GIF89a"):
        raise SlipVerificationError("ไฟล์ GIF ไม่ถูกต้อง")
    return image


def verify_bank_slip(image: str, expected_amount: Decimal, api_key: str, client: httpx.Client | None = None) -> str:
    """Return the verified bank transaction reference, or raise closed."""
    if not api_key:
        raise SlipVerificationError("ยังไม่ได้ตั้งค่า EasySlip API key")
    try:
        amount = Decimal(str(expected_amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise SlipVerificationError("ยอดบิลไม่ถูกต้อง") from exc
    if amount <= 0:
        raise SlipVerificationError("ยอดบิลต้องมากกว่าศูนย์")
    payload = {
        "base64": _validated_image(image),
        "matchAccount": True,
        "matchAmount": float(amount),
        "checkDuplicate": True,
    }
    try:
        if client is None:
            with httpx.Client(timeout=15.0) as own_client:
                response = own_client.post(EASYSLIP_VERIFY_URL, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
        else:
            response = client.post(EASYSLIP_VERIFY_URL, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SlipVerificationError("ติดต่อ EasySlip ไม่สำเร็จ กรุณาลองใหม่") from exc
    if data.get("success") is not True or not isinstance(data.get("data"), dict):
        raise SlipVerificationError("EasySlip ไม่ยืนยันสลิปนี้")
    slip = data["data"]
    if slip.get("isDuplicate") is not False:
        raise SlipVerificationError("สลิปนี้เคยใช้แล้วหรือสถานะซ้ำไม่ชัดเจน")
    if not slip.get("matchedAccount"):
        raise SlipVerificationError("บัญชีผู้รับไม่ตรงกับบัญชีร้านที่ลงทะเบียนใน EasySlip")
    if slip.get("isAmountMatched") is not True:
        raise SlipVerificationError("ยอดโอนในสลิปไม่ตรงกับยอดบิล")
    try:
        actual = Decimal(str(slip["amountInSlip"])).quantize(Decimal("0.01"))
    except (KeyError, ValueError, InvalidOperation) as exc:
        raise SlipVerificationError("EasySlip ไม่ส่งยอดเงินที่ตรวจสอบได้") from exc
    if actual != amount:
        raise SlipVerificationError("ยอดโอนในสลิปไม่ตรงกับยอดบิล")
    raw = slip.get("rawSlip") or {}
    currency = ((raw.get("amount") or {}).get("local") or {}).get("currency")
    if currency != "THB":
        raise SlipVerificationError("สลิปนี้ไม่ใช่การโอนสกุลเงินบาท")
    trans_ref = raw.get("transRef")
    if not isinstance(trans_ref, str) or not trans_ref.strip() or len(trans_ref) > 100:
        raise SlipVerificationError("ไม่พบรหัสรายการโอนที่ตรวจสอบได้")
    return trans_ref.strip()
