"""Application configuration module."""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "FastAPI Boilerplate"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

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

    # --- AI / Mistral RAG ---
    # Mistral API key used for both chat completions and embeddings.
    # Configure in your environment or .env file as: MISTRAL_API_KEY=...
    MISTRAL_API_KEY: str | None 

    # Base URL for the Mistral HTTP API.
    # Default is the public SaaS endpoint; override only if needed.
    MISTRAL_API_BASE: str = "https://api.mistral.ai"

    # Default chat model used for the chatbot endpoint.
    # Example: "mistral-small-latest", "mistral-large-latest".
    MISTRAL_MODEL: str = "mistral-small-latest"

    # Embedding model and expected dimensions for Atlas Vector Search.
    # When using Mistral embeddings, a common choice is "mistral-embed".
    # EMBEDDING_DIMENSIONS must match your Atlas vector index configuration.
    EMBEDDING_MODEL: str = "mistral-embed"
    EMBEDDING_DIMENSIONS: int | None = None
    EMBEDDING_BATCH_SIZE: int = 16
    MISTRAL_MAX_RETRIES: int = 4
    MISTRAL_RETRY_BASE_SECONDS: float = 1.0
    MISTRAL_RETRY_MAX_SECONDS: float = 20.0
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
