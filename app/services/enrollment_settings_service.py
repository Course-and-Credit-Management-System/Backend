from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.core.time_utils import normalize_to_app_timezone, now_in_app_timezone
from app.models.enrollment_setting import EnrollmentSetting
from app.schemas.enrollment_setting import StudentEnrollmentSettingResponse

logger = logging.getLogger(__name__)


def build_fallback_setting() -> StudentEnrollmentSettingResponse:
    return StudentEnrollmentSettingResponse(
        enrollment_open_at=None,
        enrollment_close_at=None,
        max_credits=18.0,
        max_courses=None,
        allow_waitlist=False,
        is_active=True,
        is_fallback=True,
    )


async def get_active_setting() -> Optional[EnrollmentSetting]:
    return await EnrollmentSetting.find_one(EnrollmentSetting.is_active == True)  # noqa: E712


async def get_effective_enrollment_settings() -> StudentEnrollmentSettingResponse:
    setting = await EnrollmentSetting.find_all().sort("-updated_at").limit(1).to_list()
    setting_doc = setting[0] if setting else None

    if not setting_doc:
        logger.warning("No active enrollment setting found. Using fallback defaults.")
        return build_fallback_setting()

    return StudentEnrollmentSettingResponse(
        enrollment_open_at=normalize_to_app_timezone(setting_doc.enrollment_open_at),
        enrollment_close_at=normalize_to_app_timezone(setting_doc.enrollment_close_at),
        max_credits=float(setting_doc.max_credits),
        max_courses=setting_doc.max_courses,
        allow_waitlist=setting_doc.allow_waitlist,
        is_active=setting_doc.is_active,
        is_fallback=False,
    )


async def get_effective_enrollment_settings_for_user(current_user: Dict[str, Any]) -> StudentEnrollmentSettingResponse:
    _ = current_user
    return await get_effective_enrollment_settings()


def enforce_enrollment_window_or_403(settings: StudentEnrollmentSettingResponse) -> None:
    if settings.is_fallback:
        return

    if not settings.is_active:
        raise HTTPException(status_code=403, detail="Enrollment is currently closed.")

    now = now_in_app_timezone()
    open_at = normalize_to_app_timezone(settings.enrollment_open_at)
    close_at = normalize_to_app_timezone(settings.enrollment_close_at)
    if open_at and now < open_at:
        raise HTTPException(status_code=403, detail="Enrollment period is not open yet.")
    if close_at and now > close_at:
        raise HTTPException(status_code=403, detail="Enrollment period is closed.")


async def assert_single_setting_or_409() -> None:
    existing = await EnrollmentSetting.find_all().limit(1).to_list()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Only one enrollment setting document is allowed. Use PUT to update it.",
        )
