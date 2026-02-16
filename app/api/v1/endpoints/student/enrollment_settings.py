from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps.auth import get_current_user
from app.schemas.enrollment_setting import StudentEnrollmentSettingResponse
from app.services.enrollment_settings_service import get_effective_enrollment_settings_for_user

router = APIRouter(prefix="/student/enrollment/settings", tags=["student-enrollment-settings"])


@router.get("/current", response_model=StudentEnrollmentSettingResponse)
async def get_current_enrollment_settings(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    if not current_user.get("student_profile"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a student",
        )
    return await get_effective_enrollment_settings_for_user(current_user=current_user)
