from datetime import datetime
from typing import Optional
from beanie import Document, PydanticObjectId
from pydantic import Field

class Alert(Document):
    id: Optional[PydanticObjectId] = Field(default=None, alias="_id")
    student_id: str
    message: str
    is_read: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "Alerts"
        indexes = [
            "student_id",
            "is_read"
        ]
