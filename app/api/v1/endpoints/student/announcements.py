from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_database
from app.api.v1.deps.auth import get_current_user

router = APIRouter()

async def _get_col(db, names: list[str]):
    cols = await db.list_collection_names()
    for n in names:
        if n in cols:
            return db[n]
    return db[names[0]]

def _to_iso(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)

@router.get("/announcements", tags=["student"])
async def list_student_announcements(current_user=Depends(get_current_user)):
    db = await get_database()
    anns = await _get_col(db, ["Announcements", "announcements"])
    users = await _get_col(db, ["Users", "users"])
    user = await users.find_one({"user_id": current_user["user_id"]}) or {}
    read_ids = set((user.get("announcement_reads") or []))

    items = []
    async for doc in anns.find({"status": {"$in": ["published", None]}}).sort("date_posted", -1):
        doc["_id"] = str(doc.get("_id"))
        doc["date_posted"] = _to_iso(doc.get("date_posted"))
        doc["expiry_date"] = _to_iso(doc.get("expiry_date"))
        doc["is_read"] = doc["_id"] in read_ids
        items.append(doc)
    return items

@router.get("/announcements/unread-count", tags=["student"])
async def unread_count(current_user=Depends(get_current_user)):
    db = await get_database()
    anns = await _get_col(db, ["Announcements", "announcements"])
    users = await _get_col(db, ["Users", "users"])
    user = await users.find_one({"user_id": current_user["user_id"]}) or {}
    read_ids = set((user.get("announcement_reads") or []))
    total = await anns.count_documents({"status": {"$in": ["published", None]}})
    # Count unread by subtracting read_ids present in DB
    unread = 0
    async for doc in anns.find({"status": {"$in": ["published", None]}}, {"_id": 1}):
        if str(doc.get("_id")) not in read_ids:
            unread += 1
    return {"count": unread, "total": total}

@router.post("/announcements/mark-read", tags=["student"])
async def mark_read(payload: dict, current_user=Depends(get_current_user)):
    db = await get_database()
    users = await _get_col(db, ["Users", "users"])
    user = await users.find_one({"user_id": current_user["user_id"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    read_ids = set((user.get("announcement_reads") or []))
    anns = await _get_col(db, ["Announcements", "announcements"])

    if payload.get("all"):
        ids = []
        async for doc in anns.find({"status": {"$in": ["published", None]}}, {"_id": 1}):
            ids.append(str(doc.get("_id")))
        read_ids.update(ids)
    else:
        aid = str(payload.get("announcement_id") or "").strip()
        if not aid:
            raise HTTPException(status_code=422, detail="announcement_id required")
        read_ids.add(aid)

    await users.update_one(
        {"user_id": current_user["user_id"]},
        {"$set": {"announcement_reads": list(read_ids), "updated_at": datetime.utcnow()}}
    )
    return {"success": True}
