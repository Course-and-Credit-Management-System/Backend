from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import HTTPException

from app.core.database import get_database


COLLECTION = "Messages"


# ============================================================
# Helpers
# ============================================================

def _student_id(student: Any) -> str:
    """
    Keeps same behavior style as _admin_id but for student.
    """
    if isinstance(student, dict):
        return student.get("user_id") or student.get("id") or "STD-UNKNOWN"
    return getattr(student, "user_id", None) or getattr(student, "id", None) or "STD-UNKNOWN"


def _ensure_str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ============================================================
# Student Service functions
# ============================================================

async def list_student_messages(student: Any) -> List[Dict[str, Any]]:
    """
    Student sees messages where they are the receiver_id.
    """
    db = await get_database()
    student_id = _student_id(student)

    msgs = (
        await db[COLLECTION]
        .find({"receiver_id": student_id})
        .sort("sent_at", -1)
        .to_list(length=2000)
    )

    out: List[Dict[str, Any]] = []
    for m in msgs:
        _ensure_str_id(m)

        # Student read flag (optional)
        read_by_students = m.get("read_by_students") or []
        m["is_read"] = student_id in read_by_students

        # don't leak internal lists
        if "read_by_admins" in m:
            del m["read_by_admins"]
        if "read_by_students" in m:
            del m["read_by_students"]

        out.append(m)

    return out


async def mark_student_message_read(message_id: str, is_read: bool, student: Any) -> Dict[str, Any]:
    """
    Student toggles read/unread for themselves.
    """
    db = await get_database()
    student_id = _student_id(student)

    if is_read:
        update = {"$addToSet": {"read_by_students": student_id}}
    else:
        update = {"$pull": {"read_by_students": student_id}}

    res = await db[COLLECTION].update_one(
        {"_id": message_id, "receiver_id": student_id},  # ✅ prevents reading others' messages
        update,
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    return {"message": "Message updated"}


async def delete_student_message(message_id: str, student: Any) -> Dict[str, Any]:
    """
    Optional: student deletes only their own message copy.
    If you don't want students to delete, remove this function.
    """
    db = await get_database()
    student_id = _student_id(student)

    res = await db[COLLECTION].delete_one({"_id": message_id, "receiver_id": student_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    return {"message": "Message deleted"}
