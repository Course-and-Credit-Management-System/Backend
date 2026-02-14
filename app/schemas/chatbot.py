from typing import List, Literal, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    message: str
    course_id: Optional[str] = None
    history: List[ChatMessage] = []
    mode: Literal[
        "auto",
        "course_selection",
        "course_stats",
        "course_advisor",
        "academic_progress",
        "major_requirements",
        "announcements",
        "policy_general",
    ] = "auto"


class ChatSource(BaseModel):
    text: str
    source: Optional[str] = None
    score: Optional[float] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[ChatSource] = []
