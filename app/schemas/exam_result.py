from pydantic import BaseModel, Field, model_validator, field_validator
from typing import Optional, Literal

Section = Literal["A", "B", "C"]
Semester = Literal[1, 2]
Major = Literal["SE", "KE", "HPC", "CSec", "CN", "BIS", "ES", "CS", "CT"]

class ExamResultUpsertIn(BaseModel):
    student_id: str
    course_code: str
    year: int = Field(ge=1, le=5)
    semester: int = Field(ge=1, le=2)
    major: Optional[str] = None  # Required for year 4-5; accept any string for malformed records
    section: Optional[str] = None  # Required for year 1-3; A/B/C
    exam_score: float = Field(ge=0, le=100)  # Any score 0-100, including under 60

    @field_validator("year", "semester", mode="before")
    @classmethod
    def coerce_int(cls, v):
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return 1
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        try:
            return int(float(v)) if v is not None else 1
        except (TypeError, ValueError):
            return 1

    @model_validator(mode='after')
    def validate_section_and_major(self):
        """Normalize section/major so malformed records (e.g. missing section/major) still save."""
        if self.year in [1, 2]:
            if not self.section or str(self.section).strip() not in ("A", "B", "C"):
                self.section = "A"
            self.major = None
        elif self.year == 3:
            if not self.section or str(self.section).strip() not in ("A", "B", "C"):
                self.section = "A"
            if not self.major or str(self.major).strip() not in ("CS", "CT"):
                self.major = "CS"
        elif self.year in [4, 5]:
            self.section = None
            if not self.major or not str(self.major).strip():
                self.major = "SE"
        return self

class ExamResultOut(BaseModel):
    student_id: str
    student_name: Optional[str] = None
    course_code: str
    year: int
    semester: int  # 1 or 2
    major: Optional[str] = None
    section: Optional[str] = None  # A, B, C, or null - accept any to avoid dropping records
    exam_score: float
    grade: str
    grade_point: float
    status: str
