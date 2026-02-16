from .courses import router as courses_router
from .academic import router as academic_router
from .enrollment_settings import router as enrollment_settings_router

__all__ = ["courses_router", "academic_router", "enrollment_settings_router"]
