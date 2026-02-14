from fastapi import APIRouter, Depends
from app.api.v1.deps.auth import require_admin
from app.services.admin_dashboard_service import AdminDashboardService
from fastapi import HTTPException 
from app.core.database import get_database


router = APIRouter(prefix="/admin", tags=["admin-dashboard"])

async def svc():
    db = await get_database()
    return AdminDashboardService(db)

@router.get("/statistics")
async def statistics(_admin=Depends(require_admin), service: AdminDashboardService = Depends(svc)):
    return await service.statistics()

@router.get("/major-distribution")
async def major_distribution(_admin=Depends(require_admin), service: AdminDashboardService = Depends(svc)):
    return await service.major_distribution()

@router.get("/pending-actions")
async def pending_actions(_admin=Depends(require_admin), service: AdminDashboardService = Depends(svc)):
    return await service.pending_actions()
    
@router.get("/students-summary")
async def list_students(
    _admin=Depends(require_admin),
    service: AdminDashboardService = Depends(svc),
):
    return await service.list_students()


@router.get("/students/{student_id}")
async def student_details(
    student_id: str,
    _admin=Depends(require_admin),
    service: AdminDashboardService = Depends(svc),
):
    data = await service.get_student_details(student_id)
    if not data:
        raise HTTPException(status_code=404, detail="Student not found")
    return data