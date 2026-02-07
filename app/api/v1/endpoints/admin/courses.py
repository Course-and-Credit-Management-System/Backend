from fastapi import APIRouter, Depends, HTTPException
from app.api.v1.deps.auth import require_admin
from app.core.database import get_database
from pydantic import BaseModel
from typing import Any, Optional, List, Union
from pymongo.errors import WriteError


router = APIRouter(prefix="/admin", tags=["admin-courses"])


class CourseCreate(BaseModel):
    course_code: str
    title: str
    department: str
    credits: Union[int, float]
    type: str
    instructor: Optional[str] = None

    # ✅ accept both, but we'll store as array to satisfy Mongo validator
    schedule: Optional[Union[str, List[str]]] = None

    room: Optional[str] = None
    description: Optional[str] = None
    prerequisites: Optional[List[str]] = None


class CourseUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    credits: Optional[Union[int, float]] = None
    type: Optional[str] = None
    instructor: Optional[str] = None
    schedule: Optional[Union[str, List[str]]] = None
    room: Optional[str] = None
    description: Optional[str] = None
    prerequisites: Optional[List[str]] = None




@router.get("/courses")
async def list_courses(_admin=Depends(require_admin)):
    db = await get_database()
    courses = await db["Courses"].find({}).to_list(length=2000)

    # Safe conversion (even if _id is already a string like "c_01")
    for c in courses:
        if "_id" in c:
            c["_id"] = str(c["_id"])

    return courses


@router.get("/courses/{course_code}")
async def get_course(course_code: str, _admin=Depends(require_admin)):
    db = await get_database()

    course = await db["Courses"].find_one({"course_code": course_code})
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if "_id" in course:
        course["_id"] = str(course["_id"])

    return course


@router.post("/courses")
async def create_course(payload: CourseCreate, _admin: Any = Depends(require_admin)):
    db = await get_database()

    # prevent duplicates by course_code
    existing = await db["Courses"].find_one({"course_code": payload.course_code})
    if existing:
        raise HTTPException(status_code=400, detail="Course already exists")

    doc = payload.model_dump(exclude_none=True)

    # ✅ schema: _id must be string
    doc["_id"] = f"c_{payload.course_code}"

    # ✅ schema: credits must be double
    doc["credits"] = float(payload.credits)

    # ✅ IMPORTANT: Mongo validator expects schedule ARRAY (your current DB validator)
    if "schedule" not in doc or doc["schedule"] is None:
        doc["schedule"] = []
    elif isinstance(doc["schedule"], str):
        doc["schedule"] = [doc["schedule"]]
    elif isinstance(doc["schedule"], list):
        doc["schedule"] = doc["schedule"]

    # optional but safe: keep prerequisites as array (or empty)
    if "prerequisites" not in doc or doc["prerequisites"] is None:
        doc["prerequisites"] = []
    elif not isinstance(doc["prerequisites"], list):
        doc["prerequisites"] = [str(doc["prerequisites"])]

    try:
        await db["Courses"].insert_one(doc)
    except WriteError as e:
        # turns Mongo validation error into a clean 400 instead of 500
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Course created successfully", "_id": doc["_id"]}

@router.delete("/courses/{course_code}")
async def delete_course(course_code: str, _admin: Any = Depends(require_admin)):
    db = await get_database()

    result = await db["Courses"].delete_one({"course_code": course_code})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Course not found")

    return {"message": "Course deleted successfully"}


@router.put("/courses/{course_code}")
async def update_course(course_code: str, payload: CourseUpdate, _admin: Any = Depends(require_admin)):
    db = await get_database()

    existing = await db["Courses"].find_one({"course_code": course_code})
    if not existing:
        raise HTTPException(status_code=404, detail="Course not found")

    update = payload.model_dump(exclude_none=True)

    # credits must be double
    if "credits" in update:
        update["credits"] = float(update["credits"])

    # Mongo validator expects schedule ARRAY
    if "schedule" in update:
        if update["schedule"] is None:
            update["schedule"] = []
        elif isinstance(update["schedule"], str):
            update["schedule"] = [update["schedule"]]
        elif isinstance(update["schedule"], list):
            update["schedule"] = update["schedule"]

    # prerequisites should be array
    if "prerequisites" in update:
        if update["prerequisites"] is None:
            update["prerequisites"] = []
        elif not isinstance(update["prerequisites"], list):
            update["prerequisites"] = [str(update["prerequisites"])]

    if not update:
        return {"message": "No changes"}

    try:
        await db["Courses"].update_one({"course_code": course_code}, {"$set": update})
    except WriteError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Course updated successfully"}
