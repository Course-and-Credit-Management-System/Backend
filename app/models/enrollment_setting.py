from datetime import datetime
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


class EnrollmentSetting(Document):
    id: Optional[PydanticObjectId] = Field(default=None, alias="_id")
    enrollment_open_at: datetime
    enrollment_close_at: datetime
    max_credits: float = Field(default=24.0, gt=0)
    max_courses: Optional[int] = Field(default=None, gt=0)
    allow_waitlist: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None

    class Settings:
        name = "EnrollmentSettings"
        indexes = [
            "is_active",
            [("is_active", 1)],
        ]
        use_state_management = True
        validate_on_save = True

    class Config:
        populate_by_name = True
