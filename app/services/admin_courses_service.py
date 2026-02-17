from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from fastapi import HTTPException
from pymongo.errors import WriteError

from app.core.database import get_database


COLLECTION = "Courses"


# ============================================================
# Helpers (business rules)
# ============================================================

def _ensure_str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _normalize_str(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _normalize_schedule(value: Optional[Union[str, List[str]]]) -> List[str]:
    """
    Mongo validator expects schedule ARRAY.
    Accepts:
      - None -> []
      - str -> [str]
      - list -> list[str]
    """
    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, list):
        out: List[str] = []
        for x in value:
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    return []


def _normalize_prereqs(value: Optional[List[str] | Any]) -> List[str]:
    """
    Keep prerequisites as list[str] for validator safety.
    """
    if value is None:
        return []
    if isinstance(value, list):
        out: List[str] = []
        for x in value:
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    s = str(value).strip()
    return [s] if s else []


def _as_float_credits(v: Union[int, float]) -> float:
    try:
        return float(v)
    except Exception:
        raise HTTPException(status_code=400, detail="credits must be a number")


def _normalize_syllabus(value: Optional[Any]) -> List[Dict[str, Any]]:
    """
    syllabus must be list of objects: [{week:int, topic:str}]
    - None -> []
    - list -> cleaned list
    """
    if value is None:
        return []

    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="syllabus must be a list")

    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        week = item.get("week")
        topic = item.get("topic")

        # validate week
        try:
            week_int = int(week)
        except Exception:
            raise HTTPException(status_code=400, detail="syllabus.week must be an integer")

        if week_int <= 0:
            raise HTTPException(status_code=400, detail="syllabus.week must be >= 1")

        topic_str = str(topic).strip() if topic is not None else ""
        if not topic_str:
            raise HTTPException(status_code=400, detail="syllabus.topic is required")

        out.append({"week": week_int, "topic": topic_str})

    # sort by week, and deduplicate by week (keep last)
    dedup: Dict[int, Dict[str, Any]] = {}
    for x in out:
        dedup[x["week"]] = x

    return [dedup[w] for w in sorted(dedup.keys())]


def _normalize_semester(value: Optional[Any]) -> List[Dict[str, str]]:
    """
    ✅ FIXED: Mongo validator expects semester ARRAY OF OBJECTS:
      semester: [{ semester: "1st Year, First Sem(new)" }]

    Accepts:
      - None -> []
      - str -> [{"semester": str}]
      - list[str] -> [{"semester": s}, ...]
      - list[{"semester": "..."}] -> cleaned
    """
    if value is None:
        return []

    # allow legacy single string
    if isinstance(value, str):
        s = value.strip()
        return [{"semester": s}] if s else []

    if isinstance(value, list):
        out: List[Dict[str, str]] = []
        for item in value:
            # already object form
            if isinstance(item, dict):
                s = str(item.get("semester", "")).strip()
                if s:
                    out.append({"semester": s})
                continue

            # string form inside list
            s = str(item).strip()
            if s:
                out.append({"semester": s})

        return out

    # unknown type -> empty (safer)
    return []


# ============================================================
# Service functions
# ============================================================

async def list_courses() -> List[Dict[str, Any]]:
    db = await get_database()
    courses = await db[COLLECTION].find({}).to_list(length=2000)
    return [_ensure_str_id(c) for c in courses]


async def get_course(course_code: str) -> Dict[str, Any]:
    db = await get_database()
    course = await db[COLLECTION].find_one({"course_code": course_code})
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return _ensure_str_id(course)


async def create_course(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload is already validated by Pydantic in router.
    Here we apply DB/validator normalization.
    """
    db = await get_database()

    existing = await db[COLLECTION].find_one({"course_code": payload["course_code"]})
    if existing:
        raise HTTPException(status_code=400, detail="Course already exists")

    doc = dict(payload)

    doc["_id"] = f"c_{payload['course_code']}"
    doc["credits"] = _as_float_credits(payload["credits"])
    doc["schedule"] = _normalize_schedule(payload.get("schedule"))
    doc["prerequisites"] = _normalize_prereqs(payload.get("prerequisites"))

    # ✅ FIXED: semester must be array of objects
    doc["semester"] = _normalize_semester(payload.get("semester"))

    # ✅ syllabus
    doc["syllabus"] = _normalize_syllabus(payload.get("syllabus"))

    # ✅ NEW: major + track (optional)
    major = _normalize_str(payload.get("major"))
    track = _normalize_str(payload.get("track"))
    if major is not None:
        doc["major"] = major
    if track is not None:
        doc["track"] = track

    try:
        await db[COLLECTION].insert_one(doc)
    except WriteError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Course created successfully", "_id": doc["_id"]}


async def delete_course(course_code: str) -> Dict[str, Any]:
    db = await get_database()

    result = await db[COLLECTION].delete_one({"course_code": course_code})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Course not found")

    return {"message": "Course deleted successfully"}


async def update_course(course_code: str, update_payload: Dict[str, Any]) -> Dict[str, Any]:
    db = await get_database()

    existing = await db[COLLECTION].find_one({"course_code": course_code})
    if not existing:
        raise HTTPException(status_code=404, detail="Course not found")

    update = dict(update_payload)

    if "credits" in update:
        update["credits"] = _as_float_credits(update["credits"])

    if "schedule" in update:
        update["schedule"] = _normalize_schedule(update.get("schedule"))

    if "prerequisites" in update:
        update["prerequisites"] = _normalize_prereqs(update.get("prerequisites"))

    # ✅ FIXED: semester must be array of objects
    if "semester" in update:
        update["semester"] = _normalize_semester(update.get("semester"))

    # ✅ syllabus
    if "syllabus" in update:
        update["syllabus"] = _normalize_syllabus(update.get("syllabus"))

    # ✅ NEW: major + track (optional)
    if "major" in update:
        update["major"] = _normalize_str(update.get("major"))
        if update["major"] is None:
            del update["major"]

    if "track" in update:
        update["track"] = _normalize_str(update.get("track"))
        if update["track"] is None:
            del update["track"]

    if not update:
        return {"message": "No changes"}

    try:
        await db[COLLECTION].update_one({"course_code": course_code}, {"$set": update})
    except WriteError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Course updated successfully"}
