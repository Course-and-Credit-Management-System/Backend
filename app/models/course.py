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
    course_code: str = Field(..., unique=True, description="e.g., 'CST-1010'")
    title: str
    credits: float = Field(..., gt=0, le=6.0)
    type: CourseType
    semester: List[Dict[str, str]] = []  # Array of objects: [{"semester": "String"}]
    major_specific: bool = False
    prerequisites: List[str] = []  # List of course_code strings
    schedule: List[str] = []  # ["Mon 10:00-11:30"]
    syllabus: List[Dict[str, Any]] = []  # [{"week": Int, "topic": String}]

    class Settings:
        name = "courses"
        indexes = ["course_code"]
