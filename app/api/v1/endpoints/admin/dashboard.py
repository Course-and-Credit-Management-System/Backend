from fastapi import APIRouter, Depends
from app.api.v1.deps.auth import require_admin
from app.services.admin_dashboard_service import AdminDashboardService
from fastapi import HTTPException 
from app.core.database import get_database
from typing import List, Dict


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
    
@router.get("/students")
async def list_students(
    _admin=Depends(require_admin),
    service: AdminDashboardService = Depends(svc),
):
    return await service.list_students()

@router.get("/students/ids")
async def student_ids(_admin=Depends(require_admin), service: AdminDashboardService = Depends(svc)):
    students = await service.list_students()

    ids = []
    if isinstance(students, list):
        for s in students:
            if isinstance(s, dict) and s.get("user_id"):
                ids.append(s["user_id"])

    ids.sort()
    return ids


@router.get("/students/options")
async def student_options(_admin=Depends(require_admin)):
    db = await get_database()

    cursor = db["Users"].find(
        {"role": "student"},
        {"_id": 0, "user_id": 1, "name": 1, "full_name": 1, "first_name": 1, "last_name": 1},
    ).sort("user_id", 1)

    docs = await cursor.to_list(length=5000)

    options: List[Dict[str, str]] = []
    for d in docs:
        uid = d.get("user_id")
        if not uid:
            continue

        # try common fields; adjust if your schema differs
        name = (
            d.get("name")
            or d.get("full_name")
            or " ".join([x for x in [d.get("first_name"), d.get("last_name")] if x])
            or uid
        )

        options.append({"user_id": uid, "name": name})

    return options


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