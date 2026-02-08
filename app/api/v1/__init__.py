"""API v1 router aggregation."""
from fastapi import APIRouter

from app.api.v1.endpoints import health, users
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.admin.dashboard import router as admin_dashboard_router
from app.api.v1.endpoints.admin.courses import router as admin_courses_router
from app.api.v1.endpoints.admin.announcements import router as admin_announcements_router
from app.api.v1.endpoints.admin.messages import router as admin_messages_router
from app.api.v1.endpoints.student import courses_router as student_courses_router


api_router = APIRouter()

# existing
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(users.router, prefix="/users", tags=["users"])

# new
api_router.include_router(auth_router)             # prefix="/auth" is inside endpoints/auth.py
api_router.include_router(admin_dashboard_router)  # prefix="/admin" is inside endpoints/admin/dashboard.py
api_router.include_router(admin_courses_router)
api_router.include_router(admin_announcements_router)
api_router.include_router(admin_messages_router)

# Student
api_router.include_router(student_courses_router)
