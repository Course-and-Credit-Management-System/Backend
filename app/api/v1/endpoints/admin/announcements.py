from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime
import time

from app.api.v1.deps.auth import require_admin
from app.core.database import get_database

router = APIRouter(prefix="/admin", tags=["Admin Announcements"])


# ---------------------------------------------------
# GET ALL ANNOUNCEMENTS
# ---------------------------------------------------
from datetime import datetime

@router.get("/announcements")
async def list_announcements(admin=Depends(require_admin)):
    db = await get_database()
    col = db["Announcements"]

    def to_iso(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        # tolerate strings or other types that might already be serialized
        return str(v)

    docs = []
    async for doc in col.find().sort("date_posted", -1):
        if "date_posted" in doc:
            doc["date_posted"] = to_iso(doc.get("date_posted"))
        if "expiry_date" in doc:
            doc["expiry_date"] = to_iso(doc.get("expiry_date"))
        docs.append(doc)

    return docs


# ---------------------------------------------------
# CREATE ANNOUNCEMENT
# ---------------------------------------------------
@router.post("/announcements", status_code=status.HTTP_201_CREATED)
async def create_announcement(payload: dict, admin=Depends(require_admin)):
    db = await get_database()
    col = db["Announcements"]

    new_id = f"ann_{int(time.time())}"

    doc = {
        "_id": new_id,
        "title": payload.get("title"),
        "content": payload.get("content"),
        "type": payload.get("type", "General"),
        "posted_by": admin["user_id"],  # from JWT
        "date_posted": datetime.utcnow(),
        "target_audience": payload.get("target_audience", "All"),
        "expiry_date": None,
    }

    if payload.get("expiry_date"):
        doc["expiry_date"] = datetime.fromisoformat(payload["expiry_date"])

    await col.insert_one(doc)

    return {"message": "Announcement created", "_id": new_id}


# ---------------------------------------------------
# DELETE ANNOUNCEMENT
# ---------------------------------------------------
@router.delete("/announcements/{announcement_id}")
async def delete_announcement(announcement_id: str, admin=Depends(require_admin)):
    db = await get_database()
    col = db["Announcements"]

    result = await col.delete_one({"_id": announcement_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}


@router.put("/announcements/{announcement_id}")
async def update_announcement(announcement_id: str, payload: dict, admin=Depends(require_admin)):
    db = await get_database()
    col = db["Announcements"]

    update_doc = {}

    # allow updating these fields
    if "title" in payload:
        update_doc["title"] = payload.get("title")
    if "content" in payload:
        update_doc["content"] = payload.get("content")
    if "type" in payload:
        update_doc["type"] = payload.get("type")
    if "target_audience" in payload:
        update_doc["target_audience"] = payload.get("target_audience")

    # expiry_date: allow set to null or ISO string
    if "expiry_date" in payload:
        exp = payload.get("expiry_date")
        if exp in (None, "", "null"):
            update_doc["expiry_date"] = None
        else:
            # accept ISO with Z
            update_doc["expiry_date"] = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))

    if not update_doc:
        return {"message": "No fields to update"}

    res = await col.update_one({"_id": announcement_id}, {"$set": update_doc})

    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement updated"}