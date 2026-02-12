from typing import List
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v1.deps.auth import require_admin
from app.models.user import User
from app.models.enums import Role

router = APIRouter(prefix="/admin", tags=["admin-students"])

class StudentOption(BaseModel):
    user_id: str
    name: str
    display_text: str  # Format: "TNT-8801 - Nguyen Van A"

@router.get("/students", response_model=List[StudentOption])
async def list_students_options(
    _admin=Depends(require_admin)
):
    """
    List all students for dropdown/search.
    Returns: student code, name, and formatted label.
    """
    # Fetch all students sorted by user_id
    students = await User.find(User.role == Role.STUDENT).sort(User.user_id).to_list()
    
    results = []
    for s in students:
        display = f"{s.user_id} - {s.name}"
        results.append(StudentOption(
            user_id=s.user_id,
            name=s.name,
            display_text=display
        ))
        
    return results
