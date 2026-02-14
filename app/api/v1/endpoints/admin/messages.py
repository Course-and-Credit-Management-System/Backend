from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any, Optional, List

from app.api.v1.deps.auth import require_admin
from app.services.admin_messages_service import (
    list_messages,
    send_message,
    mark_message_read,
    delete_message,
)

router = APIRouter(prefix="/admin", tags=["admin-messages"])


class MessageCreate(BaseModel):
    receiver_id: str
    subject: str
    body: str
    category: Optional[str] = "General"
    attachments: Optional[List[str]] = None


class MessageReadUpdate(BaseModel):
    is_read: bool


@router.get("/messages")
async def api_list_messages(admin: Any = Depends(require_admin)):
    return await list_messages(admin)


@router.post("/messages")
async def api_send_message(payload: MessageCreate, admin: Any = Depends(require_admin)):
    return await send_message(payload.model_dump(exclude_none=True), admin)


@router.put("/messages/{message_id}/read")
async def api_mark_message_read(message_id: str, payload: MessageReadUpdate, admin: Any = Depends(require_admin)):
    return await mark_message_read(message_id, payload.is_read, admin)


@router.delete("/messages/{message_id}")
async def api_delete_message(message_id: str, _admin: Any = Depends(require_admin)):
    return await delete_message(message_id)
