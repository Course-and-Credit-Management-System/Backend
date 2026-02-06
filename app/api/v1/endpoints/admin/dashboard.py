from fastapi import APIRouter, Depends
from app.api.v1.deps.auth import require_admin
from app.services.admin_dashboard_service import AdminDashboardService

router = APIRouter(prefix="/admin", tags=["admin-dashboard"])

def svc():
    return AdminDashboardService()

@router.get("/statistics")
async def statistics(_admin=Depends(require_admin), service: AdminDashboardService = Depends(svc)):
    return await service.statistics()

@router.get("/major-distribution")
async def major_distribution(_admin=Depends(require_admin), service: AdminDashboardService = Depends(svc)):
    return await service.major_distribution()

@router.get("/pending-actions")
async def pending_actions(_admin=Depends(require_admin), service: AdminDashboardService = Depends(svc)):
    return await service.pending_actions()
