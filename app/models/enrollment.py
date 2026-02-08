from typing import Optional
from beanie import Document
from pydantic import Field
from enum import Enum

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
    student_id: str = Field(..., description="Ref to User.user_id")
    course_id: str = Field(..., description="Ref to Course.course_code")
    semester_attend: str = Field(..., alias="semesterAttend", description="e.g., 'First Year, First Sem(old)'")
    is_retake: bool = False
    status: EnrollmentStatus
    grade: Optional[Grade] = None
    points: Optional[float] = None  # Grade points for GPA (e.g., 4.0, 2.33)
    scores: Optional[float] = None  # Raw numeric score (e.g., 85.5)

    class Settings:
        name = "enrollments"
        indexes = ["student_id", "course_id", "status"]
