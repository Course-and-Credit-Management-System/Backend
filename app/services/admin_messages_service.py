from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import uuid
from fastapi import HTTPException
from pymongo.errors import WriteError, DuplicateKeyError

from app.core.database import get_database


COLLECTION = "Messages"


# ============================================================
# Helpers
# ============================================================

def _admin_id(admin: Any) -> str:
    if isinstance(admin, dict):
        return admin.get("user_id") or admin.get("id") or "ADM-UNKNOWN"
    return getattr(admin, "user_id", None) or getattr(admin, "id", None) or "ADM-UNKNOWN"


def _ensure_str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ============================================================
# Service functions
# ============================================================

async def list_messages(admin: Any) -> List[Dict[str, Any]]:
    """
    Admin sees messages they SENT.
    - is_read = student read flag (stored in DB)
    - is_read_by_admin = computed from read_by_admins
    """
    db = await get_database()
    admin_id = _admin_id(admin)

    msgs = (
        await db[COLLECTION]
        .find({"sender_id": admin_id})
        .sort("sent_at", -1)
        .to_list(length=2000)
    )

    out: List[Dict[str, Any]] = []
    for m in msgs:
        _ensure_str_id(m)

        read_by_admins = m.get("read_by_admins") or []
        m["is_read_by_admin"] = admin_id in read_by_admins

        # keep is_read as the DB field (student read badge)
        m["is_read"] = bool(m.get("is_read", False))

        # don't leak internal list unless you want it
        if "read_by_admins" in m:
            del m["read_by_admins"]

        out.append(m)

    return out


async def send_message(payload: Dict[str, Any], admin: Any) -> Dict[str, Any]:
    db = await get_database()

    receiver_id = (payload.get("receiver_id") or "").strip()
    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "").strip()
    category = (payload.get("category") or "General").strip()
    attachments = payload.get("attachments")

    if not receiver_id or not subject or not body:
        raise HTTPException(status_code=422, detail="receiver_id, subject, and body are required")

    # Validate receiver exists AND is a student
    receiver = await db["Users"].find_one({"user_id": receiver_id, "role": "student"})
    if not receiver:
        raise HTTPException(status_code=400, detail="Student not found")

    sender_id = _admin_id(admin)
    new_id = f"msg_{uuid.uuid4().hex}"

    doc: Dict[str, Any] = {
        "_id": new_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "subject": subject,
        "body": body,
        "sent_at": datetime.utcnow(),
        "is_read": False,          # ✅ REQUIRED by your validator
        "read_by_admins": [],      # ✅ keep if validator allows it
        "category": category or "General",
    }

    if attachments is not None:
        doc["attachments"] = attachments

    try:
        await db[COLLECTION].insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Message ID collision. Please retry.")
    except WriteError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Message sent", "_id": new_id}


async def mark_message_read(message_id: str, is_read: bool, admin: Any) -> Dict[str, Any]:
    """
    This marks whether THIS ADMIN has viewed the message (read_by_admins).
    It does NOT change student read state (is_read).
    """
    db = await get_database()
    admin_id = _admin_id(admin)

    if is_read:
        update = {"$addToSet": {"read_by_admins": admin_id}}
    else:
        update = {"$pull": {"read_by_admins": admin_id}}

    res = await db[COLLECTION].update_one({"_id": message_id}, update)
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    return {"message": "Message updated"}


async def delete_message(message_id: str) -> Dict[str, Any]:
    db = await get_database()

    res = await db[COLLECTION].delete_one({"_id": message_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    return {"message": "Message deleted"}
