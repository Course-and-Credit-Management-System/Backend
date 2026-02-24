from typing import Optional
from beanie import Document, PydanticObjectId
from pydantic import Field, model_validator
from enum import Enum
from app.services.enrollment_academic_year_service import compute_enrollment_academic_year

class EnrollmentStatus(str, Enum):
    ENROLLED = "Enrolled"
    PENDING = "Pending"
    CONFLICT = "Conflict"
    WAITLISTED = "Waitlisted"
    COMPLETED = "Completed"
    DROPPED = "Dropped"
    WITHDRAWN = "Withdrawn"
    FAILED = "Failed"
    PASSED = "Passed"

class Grade(str, Enum):
    A_PLUS = "A+"
    A = "A"
    A_MINUS = "A-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"
    C_PLUS = "C+"
    C = "C"
    D = "D"
    F = "F"
    W = "W"
    I = "I"
    U = "U"
    ABS = "Abs"

class Enrollment(Document):
    id: Optional[PydanticObjectId] = Field(default=None, alias="_id")
    student_id: str = Field(..., description="Ref to User.user_id")
    course_id: str = Field(..., description="Ref to Course.course_code")
    semester_attend: str = Field(..., alias="semesterAttend", description="e.g., 'First Year, First Sem(old)'")
    academic_year: Optional[str] = Field(default=None, description="Computed label like '2024-2025'")
    is_retake: bool = False
    status: EnrollmentStatus
    
    # Validation fix: MongoDB schema validation requires these to be explicit strings/numbers/nulls?
    # Actually, the error shows "consideredValue": None, "reason": "type did not match" (expected string/double/int)
    # The MongoDB schema does NOT list them as optional/nullable in 'required' array?
    # Wait, they are NOT in 'required' array, but 'bsonType' validation fails for null if 'null' is not in bsonType list.
    
    # We must allow None in Python Pydantic, but MongoDB validation rejects strict types if value is None (Null).
    # Since we cannot change MongoDB schema easily right now, we can try to omit them if None
    # OR change the default.
    # But usually, if they are not in `required`, missing them is fine. The issue is `insert` sends `null`.
    
    grade: Optional[Grade] = Field(default=None)
    points: Optional[float] = Field(default=None)
    scores: Optional[float] = Field(default=None)
    reason: Optional[str] = Field(default=None, description="Reason for status change (e.g. admin note)")

    @model_validator(mode="after")
    def ensure_academic_year(self):
        if not self.academic_year:
            self.academic_year = compute_enrollment_academic_year(self.semester_attend)
        return self

    class Settings:
        name = "Enrollments"
        indexes = ["student_id", "course_id", "status"]
        use_state_management = True
        validate_on_save = True

    class Config:
        populate_by_name = True

