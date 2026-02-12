from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any, Optional, List, Union

from app.api.v1.deps.auth import require_admin
from app.services.admin_courses_service import (
    list_courses,
    get_course,
    create_course,
    update_course,
    delete_course,
)

router = APIRouter(prefix="/admin", tags=["admin-courses"])


class SyllabusItem(BaseModel):
    week: int
    topic: str


# ✅ Semester item matches Mongo validator: [{ "semester": "..." }]
class SemesterItem(BaseModel):
    semester: str


class CourseCreate(BaseModel):
    course_code: str
    title: str
    department: str
    credits: Union[int, float]
    type: str
    instructor: Optional[str] = None

    # accept both but store as array in service
    schedule: Optional[Union[str, List[str]]] = None

    room: Optional[str] = None
    description: Optional[str] = None
    prerequisites: Optional[List[str]] = None

    # ✅ NEW: semester (array of objects)
    semester: Optional[List[SemesterItem]] = None

    # ✅ syllabus
    syllabus: Optional[List[SyllabusItem]] = None


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

    # ✅ NEW: semester (array of objects)
    semester: Optional[List[SemesterItem]] = None

    # ✅ syllabus
    syllabus: Optional[List[SyllabusItem]] = None



@router.get("/courses")
async def api_list_courses(_admin=Depends(require_admin)):
    return await list_courses()


@router.get("/courses/{course_code}")
async def api_get_course(course_code: str, _admin=Depends(require_admin)):
    return await get_course(course_code)


@router.post("/courses")
async def api_create_course(payload: CourseCreate, _admin: Any = Depends(require_admin)):
    return await create_course(payload.model_dump(exclude_none=True))


@router.put("/courses/{course_code}")
async def api_update_course(course_code: str, payload: CourseUpdate, _admin: Any = Depends(require_admin)):
    return await update_course(course_code, payload.model_dump(exclude_none=True))


@router.delete("/courses/{course_code}")
async def api_delete_course(course_code: str, _admin: Any = Depends(require_admin)):
    return await delete_course(course_code)
