from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ExamResult(BaseModel):
    student_id: str
    course_code: str
    year: int  # 1-5
    semester: int  # 1 or 2
    section: Optional[str] = None  # A, B, C (only for years 1-3)
    major: Optional[str] = None  # CS, CT for year 3; SE, KE, etc. for years 4-5

    exam_score: float  # 0–100
    grade: str         # A+, A, B+, ...
    grade_point: float  # 4.0, 3.3, ...
    status: str        # Passed / Failed / Probation

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
