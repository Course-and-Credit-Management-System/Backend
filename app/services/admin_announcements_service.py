from __future__ import annotations

from datetime import datetime, timezone
import time
import re
from typing import Any, Dict, Optional, List

from fastapi import HTTPException
from app.core.database import get_database


# ============================================================
# Constants
# ============================================================

COLLECTION = "Announcements"


# ============================================================
# Helpers (moved from router)
# ============================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat()
    return v


def parse_iso_dt(v: Any) -> Optional[datetime]:
    """
    Accept:
      - None / "" / "null" => None
      - datetime => tz-aware utc
      - ISO string with/without Z => tz-aware utc
    """
    if v in (None, "", "null"):
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    s = str(v).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_type(v: Any) -> str:
    """
    IMPORTANT: keep Title Case to satisfy your Atlas validator enum:
      ["General","Urgent","Event","Academic"]
    Accepts lowercase too.
    """
    if not v:
        return "General"
    s = str(v).strip().lower()
    mapping = {
        "general": "General",
        "urgent": "Urgent",
        "event": "Event",
        "academic": "Academic",
    }
    return mapping.get(s, "General")


def normalize_status(v: Any) -> str:
    """
    New field (optional): draft|published|archived
    """
    if not v:
        return "draft"
    s = str(v).strip().lower()
    if s not in ("draft", "published", "archived"):
        return "draft"
    return s


def validate_announcement_payload(payload: Dict[str, Any]) -> None:
    # title/content basics
    if "title" in payload:
        if not payload["title"] or not str(payload["title"]).strip():
            raise HTTPException(status_code=400, detail="title cannot be empty")

    if "content" in payload:
        if not payload["content"] or not str(payload["content"]).strip():
            raise HTTPException(status_code=400, detail="content cannot be empty")

    # expiry rules placeholder (you can add policy later)
    if "expiry_date" in payload:
        _ = parse_iso_dt(payload.get("expiry_date"))


def serialize_announcement(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure frontend continues to work:
      - Keep legacy fields (title, content, type, posted_by, date_posted, target_audience, expiry_date)
      - Serialize datetimes to ISO
      - Add new fields safely (status/pinned/etc.)
    """
    doc.setdefault("type", "General")
    doc.setdefault("target_audience", "All")

    # Normalize type back to Title Case if stored differently
    doc["type"] = normalize_type(doc.get("type"))

    for k in (
        "date_posted",
        "expiry_date",
        "created_at",
        "updated_at",
        "published_at",
        "archived_at",
        "pinned_at",
    ):
        if k in doc:
            doc[k] = to_iso(doc.get(k))

    return doc


# ============================================================
# Service: list / get / create / update / delete
# ============================================================

async def list_announcements(
    *,
    status_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    pinned: Optional[bool] = None,
    q: Optional[str] = None,
    include_expired: bool = True,
    sort: str = "pinned_newest",
) -> List[Dict[str, Any]]:
    db = await get_database()
    col = db[COLLECTION]

    query: Dict[str, Any] = {}

    if status_filter:
        query["status"] = normalize_status(status_filter)

    if type_filter:
        query["type"] = normalize_type(type_filter)

    if pinned is not None:
        query["pinned"] = pinned

    if q:
        safe = re.escape(q.strip())
        query["$or"] = [
            {"_id": {"$regex": safe, "$options": "i"}},
            {"title": {"$regex": safe, "$options": "i"}},
            {"content": {"$regex": safe, "$options": "i"}},
            {"posted_by": {"$regex": safe, "$options": "i"}},
            {"target_audience": {"$regex": safe, "$options": "i"}},
        ]

    if not include_expired:
        now = utcnow()
        # NOTE: If $or already exists from q-search, we'd need $and.
        # Keep current behavior simple & matching your file: expiry-only $or.
        query["$or"] = [{"expiry_date": None}, {"expiry_date": {"$gt": now}}]

    # Sorting
    if sort == "oldest":
        sort_spec = [("date_posted", 1)]
    elif sort == "newest":
        sort_spec = [("date_posted", -1)]
    elif sort == "expiringSoon":
        sort_spec = [("expiry_date", 1), ("date_posted", -1)]
    else:
        sort_spec = [("pinned", -1), ("pinned_at", -1), ("date_posted", -1)]

    docs: List[Dict[str, Any]] = []
    async for doc in col.find(query).sort(sort_spec):
        docs.append(serialize_announcement(doc))

    return docs


async def get_announcement(announcement_id: str) -> Dict[str, Any]:
    db = await get_database()
    col = db[COLLECTION]

    doc = await col.find_one({"_id": announcement_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return serialize_announcement(doc)


async def create_announcement(payload: Dict[str, Any], admin_user_id: str) -> Dict[str, Any]:
    validate_announcement_payload(payload)

    db = await get_database()
    col = db[COLLECTION]

    new_id = f"ann_{int(time.time())}"
    now = utcnow()

    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content are required")

    ann_type = normalize_type(payload.get("type"))
    expiry_dt = parse_iso_dt(payload.get("expiry_date"))
    target_audience = (payload.get("target_audience") or "All")

    ann_status = normalize_status(payload.get("status"))
    pinned_val = bool(payload.get("pinned", False))

    doc = {
        "_id": new_id,
        "title": title,
        "content": content,
        "type": ann_type,
        "posted_by": admin_user_id,
        "date_posted": now,
        "target_audience": target_audience,
        "expiry_date": expiry_dt,

        # production fields
        "status": ann_status,
        "pinned": pinned_val,
        "pinned_at": now if pinned_val else None,
        "created_at": now,
        "updated_at": now,
        "published_at": now if ann_status == "published" else None,
        "archived_at": None,
    }

    await col.insert_one(doc)
    return {"message": "Announcement created", "_id": new_id}


async def update_announcement(announcement_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    validate_announcement_payload(payload)

    db = await get_database()
    col = db[COLLECTION]
    now = utcnow()

    update_doc: Dict[str, Any] = {"updated_at": now}

    if "title" in payload:
        t = str(payload.get("title") or "").strip()
        if not t:
            raise HTTPException(status_code=400, detail="title cannot be empty")
        update_doc["title"] = t

    if "content" in payload:
        c = str(payload.get("content") or "").strip()
        if not c:
            raise HTTPException(status_code=400, detail="content cannot be empty")
        update_doc["content"] = c

    if "type" in payload:
        update_doc["type"] = normalize_type(payload.get("type"))

    if "target_audience" in payload:
        update_doc["target_audience"] = payload.get("target_audience") or "All"

    if "expiry_date" in payload:
        update_doc["expiry_date"] = parse_iso_dt(payload.get("expiry_date"))

    if "status" in payload:
        st = normalize_status(payload.get("status"))
        update_doc["status"] = st
        if st == "published":
            update_doc["published_at"] = now
            update_doc["archived_at"] = None
        elif st == "archived":
            update_doc["archived_at"] = now
        elif st == "draft":
            update_doc["archived_at"] = None

    if "pinned" in payload:
        p = bool(payload.get("pinned"))
        update_doc["pinned"] = p
        update_doc["pinned_at"] = now if p else None

    if list(update_doc.keys()) == ["updated_at"]:
        return {"message": "No fields to update"}

    res = await col.update_one({"_id": announcement_id}, {"$set": update_doc})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement updated"}


async def delete_announcement(announcement_id: str) -> Dict[str, Any]:
    db = await get_database()
    col = db[COLLECTION]

    result = await col.delete_one({"_id": announcement_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"message": "Announcement deleted"}


# ============================================================
# Service: workflow actions
# ============================================================

async def publish_announcement(announcement_id: str) -> Dict[str, Any]:
    db = await get_database()
    col = db[COLLECTION]
    now = utcnow()

    res = await col.update_one(
        {"_id": announcement_id},
        {"$set": {"status": "published", "published_at": now, "archived_at": None, "updated_at": now}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"message": "Announcement published"}


async def archive_announcement(announcement_id: str) -> Dict[str, Any]:
    db = await get_database()
    col = db[COLLECTION]
    now = utcnow()

    res = await col.update_one(
        {"_id": announcement_id},
        {"$set": {"status": "archived", "archived_at": now, "updated_at": now}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"message": "Announcement archived"}


async def pin_announcement(announcement_id: str) -> Dict[str, Any]:
    db = await get_database()
    col = db[COLLECTION]
    now = utcnow()

    res = await col.update_one(
        {"_id": announcement_id},
        {"$set": {"pinned": True, "pinned_at": now, "updated_at": now}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"message": "Announcement pinned"}


async def unpin_announcement(announcement_id: str) -> Dict[str, Any]:
    db = await get_database()
    col = db[COLLECTION]
    now = utcnow()

    res = await col.update_one(
        {"_id": announcement_id},
        {"$set": {"pinned": False, "pinned_at": None, "updated_at": now}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"message": "Announcement unpinned"}


async def duplicate_announcement(announcement_id: str, admin_user_id: str) -> Dict[str, Any]:
    db = await get_database()
    col = db[COLLECTION]
    now = utcnow()

    doc = await col.find_one({"_id": announcement_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Announcement not found")

    new_id = f"ann_{int(time.time())}"

    doc["_id"] = new_id
    doc["title"] = f"{doc.get('title', 'Untitled')} (Copy)"
    doc["status"] = "draft"
    doc["pinned"] = False
    doc["pinned_at"] = None
    doc["published_at"] = None
    doc["archived_at"] = None
    doc["posted_by"] = admin_user_id
    doc["date_posted"] = now
    doc["created_at"] = now
    doc["updated_at"] = now

    doc["type"] = normalize_type(doc.get("type"))

    await col.insert_one(doc)
    return {"message": "Announcement duplicated", "_id": new_id}


async def bulk_action(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload:
    {
      "action": "archive" | "publish" | "delete",
      "ids": ["ann_...", ...]
    }
    """
    action = str(payload.get("action", "")).strip().lower()
    ids = payload.get("ids")

    if action not in ("archive", "publish", "delete"):
        raise HTTPException(status_code=400, detail="Invalid action")
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids must be a non-empty list")

    db = await get_database()
    col = db[COLLECTION]
    now = utcnow()

    if action == "delete":
        res = await col.delete_many({"_id": {"$in": ids}})
        return {"message": "Bulk delete done", "deleted_count": res.deleted_count}

    if action == "publish":
        res = await col.update_many(
            {"_id": {"$in": ids}},
            {"$set": {"status": "published", "published_at": now, "archived_at": None, "updated_at": now}},
        )
        return {"message": "Bulk publish done", "modified_count": res.modified_count}

    res = await col.update_many(
        {"_id": {"$in": ids}},
        {"$set": {"status": "archived", "archived_at": now, "updated_at": now}},
    )
    return {"message": "Bulk archive done", "modified_count": res.modified_count}
