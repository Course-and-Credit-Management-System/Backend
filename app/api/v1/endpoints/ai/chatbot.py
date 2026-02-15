from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps.auth import get_current_user
from app.schemas.chatbot import ChatRequest, ChatResponse, ChatSource
from app.services.ai_chat_service import (
    ChatServiceError,
    MissingAIConfigError,
    RateLimitedAIError,
    chat_with_admin_model,
    chat_with_student_model,
)


router = APIRouter(prefix="/ai", tags=["ai"])


def _ensure_message(payload: ChatRequest) -> str:
    if not payload.message or not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="message must not be empty",
        )
    return payload.message.strip()


def _ensure_course_id(payload: ChatRequest) -> str:
    course_id = (payload.course_id or "").strip()
    if not course_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="course_id must not be empty",
        )
    return course_id


def _role_guard(current_user: Dict[str, Any], expected_role: str) -> None:
    role = (current_user.get("role") or "").lower()
    if role != expected_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{expected_role} role required.",
        )


def _build_sources(sources_raw: Any) -> list[ChatSource]:
    return [
        ChatSource(
            text=src.get("text", ""),
            source=src.get("source"),
            score=src.get("score"),
        )
        for src in (sources_raw or [])
    ]


@router.post("/student/chat", response_model=ChatResponse)
async def chat_with_student_ai(
    payload: ChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ChatResponse:
    _role_guard(current_user, "student")
    question = _ensure_message(payload)

    history_dicts = [m.model_dump() for m in payload.history] if payload.history else None

    try:
        answer, sources_raw = await chat_with_student_model(
            question=question,
            current_user=current_user,
            history=history_dicts,
            mode=payload.mode,
            course_id=payload.course_id,
        )
    except MissingAIConfigError as exc:
        # Configuration / secret missing – treat as a server misconfiguration.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except RateLimitedAIError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except ChatServiceError as exc:
        # Known service-layer error (e.g., Gemini API failure, vector index issue).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - safety net
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while processing chatbot request.",
        ) from exc

    return ChatResponse(answer=answer, sources=_build_sources(sources_raw))


@router.post("/admin/chat", response_model=ChatResponse)
async def chat_with_admin_ai(
    payload: ChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ChatResponse:
    _role_guard(current_user, "admin")
    question = _ensure_message(payload)
    history_dicts = [m.model_dump() for m in payload.history] if payload.history else None

    try:
        answer, sources_raw = await chat_with_admin_model(
            question=question,
            current_user=current_user,
            history=history_dicts,
            mode=payload.mode,
            course_id=payload.course_id,
        )
    except MissingAIConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except RateLimitedAIError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except ChatServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - safety net
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while processing chatbot request.",
        ) from exc

    return ChatResponse(answer=answer, sources=_build_sources(sources_raw))


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai_compat(
    payload: ChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ChatResponse:
    role = (current_user.get("role") or "").lower()
    if role == "admin":
        return await chat_with_admin_ai(payload, current_user)
    return await chat_with_student_ai(payload, current_user)


@router.post("/student/course-chat", response_model=ChatResponse)
async def chat_with_student_course_ai(
    payload: ChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ChatResponse:
    _role_guard(current_user, "student")
    question = _ensure_message(payload)
    course_id = _ensure_course_id(payload)
    history_dicts = [m.model_dump() for m in payload.history] if payload.history else None

    try:
        answer, sources_raw = await chat_with_student_model(
            question=question,
            current_user=current_user,
            history=history_dicts,
            mode="course_advisor",
            course_id=course_id,
        )
    except MissingAIConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except RateLimitedAIError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except ChatServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - safety net
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while processing chatbot request.",
        ) from exc

    return ChatResponse(answer=answer, sources=_build_sources(sources_raw))
