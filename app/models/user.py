"""User model for MongoDB using Beanie ODM."""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import Field, EmailStr, BaseModel
from beanie import Document
from app.models.enums import Role, AcademicStatus, AcademicYear, AccessLevel

class AcademicHistory(BaseModel):
    course_id: str
    course_code: str
    course_title: str
    semester: str
    credits: float
    grade: Optional[str] = None
    status: str

class MajorHistory(BaseModel):
    major_name: str
    status: str
    start_term: str
    end_term: Optional[str] = None
    major_id: str

class StudentProfile(BaseModel):
    major_id: str
    academic_status: AcademicStatus = AcademicStatus.ACTIVE
    total_credits: int = 0
    advisor_id: Optional[str] = None
    is_major_student: bool = False
    gpa: float = Field(default=0.0, ge=0, le=4.0)
    cgpa: float = Field(default=0.0, ge=0, le=4.0)
    current_sem_earned_credits: int = 0
    total_credits_completed: int = 0
    current_year: AcademicYear

class AdminProfile(BaseModel):
    department: str
    access_level: AccessLevel
    permissions: List[str] = []

class User(Document):
    """User document model for MongoDB."""
    
    # Explicitly define ID as string to allow custom IDs and prevent PydanticObjectId validation errors
    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str = Field(..., unique=True, description="Unique Identifier (e.g., 'TNT-8801', 'ADM-001')")
    name: str
    email: EmailStr
    avatar: Optional[str] = None
    role: Role
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Role-specific profiles
    student_profile: Optional[StudentProfile] = None
    admin_profile: Optional[AdminProfile] = None
    
    # Embedded histories
    academic_history: List[AcademicHistory] = []
    major_history: List[MajorHistory] = []

    class Settings:
        name = "Users"
        indexes = [
            "user_id",
            "email",
            "role"
        ]
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "username": "johndoe",
                "full_name": "John Doe",
                "is_active": True,
                "is_superuser": False,
            }
        }
