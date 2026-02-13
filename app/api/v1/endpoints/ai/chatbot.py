from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps.auth import get_current_user
from app.schemas.chatbot import ChatRequest, ChatResponse, ChatSource
from app.services.ai_chat_service import (
    ChatServiceError,
    MissingAIConfigError,
    chat_with_rag,
)


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    payload: ChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ChatResponse:
    """
    RAG-backed chatbot endpoint.

    - Authenticated via the existing JWT / cookie auth system.
    - Uses MongoDB Atlas Vector Search over the KnowledgeBase collection.
    - Calls Mistral chat API to generate the final answer.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="message must not be empty",
        )

    # Optionally, you can tie the request to the authenticated user
    # (e.g., for logging or future personalization).
    user_id = current_user.get("user_id")

    # Convert Pydantic history into plain dicts accepted by the service.
    history_dicts = [m.model_dump() for m in payload.history] if payload.history else None

    try:
        answer, sources_raw = await chat_with_rag(
            question=payload.message.strip(),
            history=history_dicts,
        )
    except MissingAIConfigError as exc:
        # Configuration / secret missing – treat as a server misconfiguration.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except ChatServiceError as exc:
        # Known service-layer error (e.g., Mistral API failure, vector index issue).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - safety net
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while processing chatbot request.",
        ) from exc

    sources = [
        ChatSource(
            text=src.get("text", ""),
            source=src.get("source"),
            score=src.get("score"),
        )
        for src in (sources_raw or [])
    ]

    return ChatResponse(answer=answer, sources=sources)

