from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class EnrollmentSettingWrite(BaseModel):
    window_minutes: Optional[int] = Field(default=None, gt=0)
    window_days: Optional[int] = Field(default=None, gt=0)
    max_credits: float = Field(default=24.0, gt=0)
    max_courses: Optional[int] = Field(default=None, gt=0)
    allow_waitlist: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def validate_period(self):
        has_minutes = self.window_minutes is not None
        has_days = self.window_days is not None
        if has_minutes and has_days:
            raise ValueError("Provide only one: window_minutes or window_days")
        if not has_minutes and not has_days:
            raise ValueError("Provide one: window_minutes or window_days")
        return self


class EnrollmentSettingStatusPatch(BaseModel):
    status: Literal["open", "closed"]


class EnrollmentSettingCreate(EnrollmentSettingWrite):
    pass


class EnrollmentSettingUpdate(EnrollmentSettingWrite):
    pass


class EnrollmentSettingResponse(BaseModel):
    id: str = Field(..., alias="_id")
    max_credits: float
    max_courses: Optional[int] = None
    allow_waitlist: bool = False
    is_active: bool = True
    enrollment_open_at: datetime
    enrollment_close_at: datetime
    created_at: datetime
    updated_at: datetime
    updated_by: Optional[str] = None

    class Config:
        populate_by_name = True


class StudentEnrollmentSettingResponse(BaseModel):
    enrollment_open_at: Optional[datetime] = None
    enrollment_close_at: Optional[datetime] = None
    max_credits: float
    max_courses: Optional[int] = None
    allow_waitlist: bool = False
    is_active: bool = True
    is_fallback: bool = False
