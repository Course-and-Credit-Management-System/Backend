from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Optional, List
from datetime import datetime
from pymongo.errors import WriteError

from app.api.v1.deps.auth import require_admin
from app.core.database import get_database

router = APIRouter(prefix="/admin", tags=["admin-messages"])


class MessageCreate(BaseModel):
    receiver_id: str
    subject: str
    body: str
    category: Optional[str] = "General"
    attachments: Optional[List[str]] = None  # optional


class MessageReadUpdate(BaseModel):
    is_read: bool


@router.get("/messages")
async def list_messages(_admin: Any = Depends(require_admin)):
    db = await get_database()
    msgs = await db["Messages"].find({}).sort("sent_at", -1).to_list(length=2000)

    for m in msgs:
        if "_id" in m:
            m["_id"] = str(m["_id"])
    return msgs


@router.post("/messages")
async def send_message(payload: MessageCreate, admin: Any = Depends(require_admin)):
    db = await get_database()

    # try to get admin id from require_admin return
    sender_id = None
    if isinstance(admin, dict):
        sender_id = admin.get("user_id") or admin.get("id")
    else:
        sender_id = getattr(admin, "user_id", None) or getattr(admin, "id", None)

    if not sender_id:
        # fallback if your require_admin doesn't return user_id
        sender_id = "ADM-UNKNOWN"

    # generate id like msg_1700000000
    new_id = f"msg_{int(datetime.utcnow().timestamp())}"

    doc = {
        "_id": new_id,
        "sender_id": sender_id,
        "receiver_id": payload.receiver_id,
        "subject": payload.subject,
        "body": payload.body,
        "sent_at": datetime.utcnow(),
        "is_read": False,
        "category": payload.category or "General",
    }

    if payload.attachments is not None:
        doc["attachments"] = payload.attachments

    try:
        await db["Messages"].insert_one(doc)
    except WriteError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Message sent", "_id": new_id}


@router.put("/messages/{message_id}/read")
async def mark_message_read(message_id: str, payload: MessageReadUpdate, _admin: Any = Depends(require_admin)):
    db = await get_database()

    res = await db["Messages"].update_one({"_id": message_id}, {"$set": {"is_read": payload.is_read}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    return {"message": "Message updated"}


@router.delete("/messages/{message_id}")
async def delete_message(message_id: str, _admin: Any = Depends(require_admin)):
    db = await get_database()

    res = await db["Messages"].delete_one({"_id": message_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    return {"message": "Message deleted"}
