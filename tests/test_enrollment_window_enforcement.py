from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.student import courses as courses_endpoint
from app.schemas.enrollment_setting import StudentEnrollmentSettingResponse


@pytest.mark.asyncio
async def test_finalize_enrollment_blocked_when_window_closed(monkeypatch):
    async def fake_effective_settings_for_user(current_user):
        return StudentEnrollmentSettingResponse(
            enrollment_open_at=datetime.utcnow() - timedelta(days=2),
            enrollment_close_at=datetime.utcnow() - timedelta(minutes=1),
            max_credits=18.0,
            max_courses=None,
            allow_waitlist=False,
            is_active=True,
            is_fallback=False,
        )

    monkeypatch.setattr(
        courses_endpoint,
        "get_effective_enrollment_settings_for_user",
        fake_effective_settings_for_user,
    )

    payload = courses_endpoint.EnrollmentRequest(selected_code="CST-1001")
    current_user = {
        "user_id": "STD-TEST",
        "student_profile": {"current_year": "1st Year, First Sem(new)"},
    }

    with pytest.raises(HTTPException) as exc:
        await courses_endpoint.finalize_enrollment(payload=payload, current_user=current_user)

    assert exc.value.status_code == 403
    assert "closed" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_finalize_enrollment_blocked_when_setting_inactive(monkeypatch):
    async def fake_effective_settings_for_user(current_user):
        return StudentEnrollmentSettingResponse(
            enrollment_open_at=datetime.utcnow() - timedelta(minutes=1),
            enrollment_close_at=datetime.utcnow() + timedelta(days=1),
            max_credits=18.0,
            max_courses=None,
            allow_waitlist=False,
            is_active=False,
            is_fallback=False,
        )

    monkeypatch.setattr(
        courses_endpoint,
        "get_effective_enrollment_settings_for_user",
        fake_effective_settings_for_user,
    )

    payload = courses_endpoint.EnrollmentRequest(selected_code="CST-1001")
    current_user = {
        "user_id": "STD-TEST",
        "student_profile": {"current_year": "1st Year, First Sem(new)"},
    }

    with pytest.raises(HTTPException) as exc:
        await courses_endpoint.finalize_enrollment(payload=payload, current_user=current_user)

    assert exc.value.status_code == 403
    assert "currently closed" in str(exc.value.detail).lower()
