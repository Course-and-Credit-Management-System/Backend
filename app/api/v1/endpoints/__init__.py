from fastapi import APIRouter

from app.api.v1.endpoints import health, users
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.admin.dashboard import router as admin_dashboard_router

api_router = APIRouter()

# existing routers
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(users.router, prefix="/users", tags=["users"])

# new routers
api_router.include_router(auth_router)            # already has prefix="/auth"
api_router.include_router(admin_dashboard_router) # already has prefix="/admin"
