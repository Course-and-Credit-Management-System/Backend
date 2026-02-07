from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import Field
from enum import Enum

class AnnouncementType(str, Enum):
    GENERAL = "General"
    URGENT = "Urgent"
    EVENT = "Event"
    ACADEMIC = "Academic"

class Announcement(Document):
    type: AnnouncementType
    title: str
    content: str
    target_audience: str = Field(..., description="'All', 'Students', 'Faculty', etc.")
    expiry_date: Optional[datetime] = None
    posted_by: str = Field(..., description="Admin ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "announcements"
        indexes = ["type", "target_audience", "expiry_date"]
