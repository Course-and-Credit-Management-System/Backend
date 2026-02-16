"""Application configuration module."""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "FastAPI Boilerplate"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    APP_TIMEZONE: str = "Asia/Yangon"

    # Database - MongoDB
    MONGODB_URL: str
    MONGODB_DB_NAME: str

    # CORS
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",

        # ✅ your current frontend (from screenshot)
        "http://192.168.31.172:3000",
        "http://localhost:3000",
        "http://localhost:3001",

        # (optional but useful)
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://192.168.31.172:5173",
    ]


    # Auth / JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Password bootstrap (only for first-time login)
    DEFAULT_PASSWORD: str = "Admin123"

    # Cookie
    COOKIE_NAME: str = "access_token"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"  # "lax" is best for local dev

    # --- Email / SMTP (Mailtrap now, SendGrid later) ---
    SMTP_HOST: str
    SMTP_PORT: int = 2525
    SMTP_USER: str
    SMTP_PASS: str
    FROM_EMAIL: str 
    FRONTEND_URL: str

    # --- AI / Gemini RAG ---
    GEMINI_API_KEY: str | None
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
    GEMINI_CHAT_MODEL: str = "gemini-2.5-pro"
    GEMINI_CHAT_FALLBACK_MODEL: str = "gemini-2.5-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIMENSIONS: int | None = 1536
    EMBEDDING_BATCH_SIZE: int = 16
    GEMINI_MAX_RETRIES: int = 4
    GEMINI_RETRY_BASE_SECONDS: float = 1.0
    GEMINI_RETRY_MAX_SECONDS: float = 20.0
    GEMINI_MAX_CONCURRENT_REQUESTS: int = 1
    GEMINI_MIN_REQUEST_INTERVAL_SECONDS: float = 0.8
    AI_RAG_K: int = 5
    AI_RAG_NUM_CANDIDATES: int = 100
    AI_RAG_SCORE_THRESHOLD: float | None = None
    KNOWLEDGE_BASE_COLLECTION: str = "KnowledgeBase"
    KNOWLEDGE_VECTOR_INDEX_NAME: str = "knowledge_vector_index"

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


# IMPORTANT: this gives you `from app.core.config import settings`
settings = get_settings()
