from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AuthCredential(BaseModel):
    user_id: str
    password_hash: str
    must_reset_password: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
