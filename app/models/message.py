from datetime import datetime
from beanie import Document
from pydantic import Field
from enum import Enum

class MessageCategory(str, Enum):
    GENERAL = "General"
    WARNING = "Warning"
    ADVISOR_NOTE = "Advisor Note"
    ENROLLMENT_ISSUE = "Enrollment Issue"

class Message(Document):
    category: MessageCategory
    content: str
    is_read: bool = False
    sender_id: str = Field(..., description="Admin ID")
    receiver_id: str = Field(..., description="Student ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "messages"
        indexes = ["sender_id", "receiver_id", "is_read"]
