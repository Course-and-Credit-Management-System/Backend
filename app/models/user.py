"""User model for MongoDB using Beanie ODM."""
from datetime import datetime
from typing import Optional
from pydantic import Field, EmailStr
from beanie import Document


class User(Document):
    """User document model for MongoDB."""
    
    email: EmailStr
    username: str = Field(..., max_length=100)
    full_name: Optional[str] = Field(None, max_length=255)
    hashed_password: str
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Settings:
        name = "users"
        indexes = [
            "email",
            "username",
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
