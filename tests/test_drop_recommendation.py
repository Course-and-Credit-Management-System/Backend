import pytest

from app.api.v1.endpoints.student import courses as courses_endpoint
from app.services.ai_chat_service import RateLimitedAIError


def _build_dashboard_payload() -> courses_endpoint.DashboardResponse:
    return courses_endpoint.DashboardResponse(
        semester_name="Year 2 First Sem (New)",
        total_credits=21.0,
        max_credits=18.0,
        courses_count=5,
        courses=[
            courses_endpoint.CourseResponse(
                tag="MAJOR",
                credits=3.0,
                title="Algorithms",
                code="CS301",
                is_retake=False,
            ),
            courses_endpoint.CourseResponse(
                tag="ELECTIVE",
                credits=3.0,
                title="Creative Media",
                code="EL201",
                is_retake=False,
            ),
            courses_endpoint.CourseResponse(
                tag="ELECTIVE",
                credits=3.0,
                title="Business Basics",
                code="EL202",
                is_retake=False,
            ),
            courses_endpoint.CourseResponse(
                tag="CORE",
                credits=6.0,
                title="Data Engineering",
                code="CS302",
                is_retake=False,
            ),
            courses_endpoint.CourseResponse(
                tag="RETAKE",
                credits=6.0,
                title="[Retake] Operating Systems",
                code="CS201",
                is_retake=True,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_drop_recommendation_caches_fallback_after_invalid_ai(monkeypatch):
    courses_endpoint._drop_ai_plan_cache.clear()
    courses_endpoint._drop_ai_cooldown_until.clear()
    courses_endpoint._drop_ai_locks.clear()

    async def fake_current_courses(current_user):
        return _build_dashboard_payload()

    calls = {"count": 0}

    async def fake_chat_with_student_model(**kwargs):
        calls["count"] += 1
        return "this is not json", []

    monkeypatch.setattr(courses_endpoint, "get_current_courses", fake_current_courses)
    monkeypatch.setattr(courses_endpoint, "chat_with_student_model", fake_chat_with_student_model)

    user = {"role": "student", "user_id": "STD-001"}

    first = await courses_endpoint.course_drop_recommendation(current_user=user)
    second = await courses_endpoint.course_drop_recommendation(current_user=user)

    assert first.exceeds_limit is True
    assert "fallback generated" in first.message
    assert second.exceeds_limit is True
    assert second.message
    assert second.elective is not None or len(second.others) > 0
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_drop_recommendation_rate_limited_returns_fallback_without_repeat_calls(monkeypatch):
    courses_endpoint._drop_ai_plan_cache.clear()
    courses_endpoint._drop_ai_cooldown_until.clear()
    courses_endpoint._drop_ai_locks.clear()

    async def fake_current_courses(current_user):
        return _build_dashboard_payload()

    calls = {"count": 0}

    async def fake_chat_with_student_model(**kwargs):
        calls["count"] += 1
        raise RateLimitedAIError("AI provider is rate-limited right now.")

    monkeypatch.setattr(courses_endpoint, "get_current_courses", fake_current_courses)
    monkeypatch.setattr(courses_endpoint, "chat_with_student_model", fake_chat_with_student_model)

    user = {"role": "student", "user_id": "STD-002"}

    first = await courses_endpoint.course_drop_recommendation(current_user=user)
    second = await courses_endpoint.course_drop_recommendation(current_user=user)

    assert first.exceeds_limit is True
    assert "fallback generated" in first.message
    assert second.exceeds_limit is True
    assert second.message
    assert second.elective is not None or len(second.others) > 0
    assert calls["count"] == 1
