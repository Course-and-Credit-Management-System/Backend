from typing import List, Optional, Dict, Any
from beanie import Document
from pydantic import Field
from enum import Enum

class CourseType(str, Enum):
    CORE = "Core"
    ELECTIVE = "Elective"
    PREREQUISITE = "Prerequisite"
    MAJOR = "Major"

class Course(Document):
    id: Optional[str] = Field(default=None, alias="_id")
    course_code: str = Field(..., unique=True, description="e.g., 'CST-1010'")
    title: str
    credits: float = Field(..., gt=0, le=6.0)
    type: CourseType
    # Changed from Dict[str, str] to Dict[str, Any] to support boolean 'major_specific' inside the object
    semester: List[Dict[str, Any]] = []  
    major_specific: bool = False
    prerequisites: List[str] = []  # List of course_code strings
    schedule: List[str] = []  # ["Mon 10:00-11:30"]
    syllabus: List[Dict[str, Any]] = []  # [{"week": Int, "topic": String}]
    instructor: Optional[str] = None
    room: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None

    class Settings:
        name = "Courses"
        indexes = ["course_code"]
        use_state_management = True
        validate_on_save = True

    # Allow string ID for legacy / custom ID format like "c_102"
    class Config:
        populate_by_name = True

