"""StudentResult model for MongoDB."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from beanie import Document, Indexed
from pydantic import Field

class StudentResultDB(Document):
    """Student academic result model for MongoDB."""
    
    # MongoDB collection configuration
    class Settings:
        name = "Users"
    
    # Student identification
    user_id: str = Indexed()
    name: str
    email: str
    role: str = "student"
    avatar: Optional[str] = None
    
    # Student profile
    student_profile: Dict[str, Any] = Field(default_factory=dict)
    major_history: List[Dict[str, Any]] = Field(default_factory=list)
    academic_history: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
