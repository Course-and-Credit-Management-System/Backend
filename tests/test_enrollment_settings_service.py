from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

import app.services.enrollment_settings_service as service
from app.schemas.enrollment_setting import StudentEnrollmentSettingResponse


def test_build_fallback_setting_defaults():
    fallback = service.build_fallback_setting()
    assert fallback.is_fallback is True
    assert fallback.max_credits == 18.0
    assert fallback.allow_waitlist is False


def test_enforce_enrollment_window_allows_fallback():
    fallback = service.build_fallback_setting()
    service.enforce_enrollment_window_or_403(fallback)


def test_enforce_enrollment_window_raises_before_open():
    now = datetime.utcnow()
    settings = StudentEnrollmentSettingResponse(
        enrollment_open_at=now + timedelta(hours=2),
        enrollment_close_at=now + timedelta(days=2),
        max_credits=18.0,
        allow_waitlist=False,
        is_active=True,
        is_fallback=False,
    )
    with pytest.raises(HTTPException) as exc:
        service.enforce_enrollment_window_or_403(settings)
    assert exc.value.status_code == 403


def test_enforce_enrollment_window_raises_after_close():
    now = datetime.utcnow()
    settings = StudentEnrollmentSettingResponse(
        enrollment_open_at=now - timedelta(days=4),
        enrollment_close_at=now - timedelta(hours=1),
        max_credits=18.0,
        allow_waitlist=False,
        is_active=True,
        is_fallback=False,
    )
    with pytest.raises(HTTPException) as exc:
        service.enforce_enrollment_window_or_403(settings)
    assert exc.value.status_code == 403
