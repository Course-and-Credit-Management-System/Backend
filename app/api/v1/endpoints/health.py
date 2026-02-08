"""Health check endpoint."""
from fastapi import APIRouter, status
from datetime import datetime

from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint to verify system status."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check():
    """Readiness check for orchestration systems."""
    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat(),
    }
