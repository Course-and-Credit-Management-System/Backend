from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any

# ✅ change this import if your student auth dep has a different name/path
from app.api.v1.deps.auth import get_current_user

from app.services.student_message_service import (
    list_student_messages,
    mark_student_message_read,
    delete_student_message,
)

router = APIRouter(prefix="/student", tags=["student-messages"])


class MessageReadUpdate(BaseModel):
    is_read: bool


@router.get("/messages")
async def api_list_student_messages(student: Any = Depends(get_current_user)):
    return await list_student_messages(student)


@router.put("/messages/{message_id}/read")
async def api_mark_student_message_read(
    message_id: str,
    payload: MessageReadUpdate,
    student: Any = Depends(get_current_user),
):
    return await mark_student_message_read(message_id, payload.is_read, student)


@router.delete("/messages/{message_id}")
async def api_delete_student_message(message_id: str, student: Any = Depends(get_current_user)):
    return await delete_student_message(message_id, student)
