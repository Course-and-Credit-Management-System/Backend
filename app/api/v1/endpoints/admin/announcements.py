from fastapi import APIRouter, Depends, Query, status
from typing import Optional

from app.api.v1.deps.auth import require_admin

from app.services.admin_announcements_service import (
    list_announcements,
    get_announcement,
    create_announcement,
    update_announcement,
    delete_announcement,
    publish_announcement,
    archive_announcement,
    pin_announcement,
    unpin_announcement,
    duplicate_announcement,
    bulk_action,
)

router = APIRouter(prefix="/admin", tags=["Admin Announcements"])


# ============================================================
# GET: List announcements (Admin)
# ============================================================
@router.get("/announcements")
async def api_list_announcements(
    admin=Depends(require_admin),
    status_filter: Optional[str] = Query(None, alias="status"),
    type_filter: Optional[str] = Query(None, alias="type"),
    pinned: Optional[bool] = None,
    q: Optional[str] = None,
    include_expired: bool = True,
    sort: str = "pinned_newest",
):
    return await list_announcements(
        status_filter=status_filter,
        type_filter=type_filter,
        pinned=pinned,
        q=q,
        include_expired=include_expired,
        sort=sort,
    )


# ============================================================
# GET ONE (Admin)
# ============================================================
@router.get("/announcements/{announcement_id}")
async def api_get_announcement(announcement_id: str, admin=Depends(require_admin)):
    return await get_announcement(announcement_id)


# ============================================================
# POST: Create (Admin)
# ============================================================
@router.post("/announcements", status_code=status.HTTP_201_CREATED)
async def api_create_announcement(payload: dict, admin=Depends(require_admin)):
    return await create_announcement(payload, admin_user_id=admin["user_id"])


# ============================================================
# PUT: Update (Admin)
# ============================================================
@router.put("/announcements/{announcement_id}")
async def api_update_announcement(announcement_id: str, payload: dict, admin=Depends(require_admin)):
    return await update_announcement(announcement_id, payload)


# ============================================================
# DELETE: Delete (Admin)
# ============================================================
@router.delete("/announcements/{announcement_id}")
async def api_delete_announcement(announcement_id: str, admin=Depends(require_admin)):
    return await delete_announcement(announcement_id)


# ============================================================
# Workflow Action Endpoints (Admin)
# ============================================================
@router.post("/announcements/{announcement_id}/publish")
async def api_publish_announcement(announcement_id: str, admin=Depends(require_admin)):
    return await publish_announcement(announcement_id)


@router.post("/announcements/{announcement_id}/archive")
async def api_archive_announcement(announcement_id: str, admin=Depends(require_admin)):
    return await archive_announcement(announcement_id)


@router.post("/announcements/{announcement_id}/pin")
async def api_pin_announcement(announcement_id: str, admin=Depends(require_admin)):
    return await pin_announcement(announcement_id)


@router.post("/announcements/{announcement_id}/unpin")
async def api_unpin_announcement(announcement_id: str, admin=Depends(require_admin)):
    return await unpin_announcement(announcement_id)


@router.post("/announcements/{announcement_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def api_duplicate_announcement(announcement_id: str, admin=Depends(require_admin)):
    return await duplicate_announcement(announcement_id, admin_user_id=admin["user_id"])


@router.post("/announcements/bulk")
async def api_bulk_action(payload: dict, admin=Depends(require_admin)):
    return await bulk_action(payload)
