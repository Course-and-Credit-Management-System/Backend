from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Body, Path, Query
from pydantic import BaseModel

from app.api.v1.deps.auth import require_admin
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import User
from app.models.course import Course
from app.models.alert import Alert
from bson import ObjectId
from beanie import PydanticObjectId
from beanie.operators import In

router = APIRouter()

class EnrollmentStatusUpdate(BaseModel):
    status: EnrollmentStatus
    reason: Optional[str] = None

class AdminEnrollmentCreate(BaseModel):
    student_id: str
    course_id: str

class EnrollmentDetail(Enrollment):
    student_name: Optional[str] = None
    student_avatar: Optional[str] = None
    course_title: Optional[str] = None

@router.post("/", response_model=Enrollment, status_code=201)
async def create_enrollment(
    payload: AdminEnrollmentCreate,
    current_user: Dict[str, Any] = Depends(require_admin)
):
    """
    Manually enroll a student in a course.
    Automatically fetches the semester from the student's current_year.
    """
    # 1. Validate Student (raw read to tolerate legacy current_year values)
    student = await User.get_motor_collection().find_one(
        {"user_id": payload.student_id},
        {"user_id": 1, "student_profile.current_year": 1},
    )
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # 2. Determine Semester (Always from Student Profile)
    student_profile = student.get("student_profile") or {}
    current_year = student_profile.get("current_year")
    if not current_year:
        raise HTTPException(status_code=400, detail="Student has no valid profile or current_year")
    semester_attend = str(current_year)

    # 3. Validate Course
    course = await Course.find_one(Course.course_code == payload.course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # 4. Check Duplication
    exists = await Enrollment.find_one(
        Enrollment.student_id == payload.student_id,
        Enrollment.course_id == payload.course_id,
        Enrollment.semester_attend == semester_attend
    )
    if exists:
         raise HTTPException(status_code=409, detail="Enrollment already exists for this student in this course/semester")

    # 5. Create Enrollment
    new_enrollment = Enrollment(
        student_id=payload.student_id,
        course_id=payload.course_id,
        semester_attend=semester_attend,
        status=EnrollmentStatus.ENROLLED,  # Admin action implies immediate enrollment
        is_retake=False # Default
    )

    # Insert safely to avoid null validation errors on optional fields
    doc = new_enrollment.model_dump(by_alias=True, exclude_none=True)
    result = await Enrollment.get_motor_collection().insert_one(doc)
    new_enrollment.id = PydanticObjectId(result.inserted_id)

    # 6. Alert Student
    await Alert(
        student_id=new_enrollment.student_id,
        message=f"You have been manually enrolled in {course.title} ({course.course_code})"
    ).insert()

    return new_enrollment

@router.get("/", response_model=List[EnrollmentDetail])
async def list_enrollments(
    status: Optional[List[EnrollmentStatus]] = Query(
        default=[EnrollmentStatus.PENDING, EnrollmentStatus.ENROLLED],
        description="Filter by enrollment status (default: Pending & Enrolled)"
    ),
    skip: int = 0,
    limit: int = 100,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    """
    List enrollments. Defaults to filtering for 'Pending' and 'Enrolled' status only.
    Use ?status=Pending&status=Withdrawn to override.
    """
    
    query_filters = []
    if status:
        query_filters.append(In(Enrollment.status, status))
        
    query = Enrollment.find(*query_filters).skip(skip).limit(limit)
    enrollments = await query.to_list()
    
    # Enrich with student names and course titles
    student_ids = list({e.student_id for e in enrollments})
    course_ids = list({e.course_id for e in enrollments})
    
    student_docs = await User.get_motor_collection().find(
        {"user_id": {"$in": student_ids}},
        {"user_id": 1, "name": 1, "avatar": 1},
    ).to_list(length=None)
    courses = await Course.find(In(Course.course_code, course_ids)).to_list()
    
    student_map = {
        str(s.get("user_id")): {
            "name": s.get("name"),
            "avatar": s.get("avatar"),
        }
        for s in student_docs
    }
    course_map = {c.course_code: c.title for c in courses}
    
    results = []
    for e in enrollments:
        # Pydantic models are immutable by default if they are frozen, but Beanie Documents aren't usually.
        # However, converting to dict and back to new model is safer/cleaner.
        e_dict = e.dict(by_alias=True)
        student_info = student_map.get(e.student_id, {"name": "Unknown", "avatar": None})
        e_dict["student_name"] = student_info["name"]
        e_dict["student_avatar"] = student_info["avatar"]
        e_dict["course_title"] = course_map.get(e.course_id, "Unknown")
        results.append(e_dict)
        
    return results

@router.put("/{enrollment_id}/status", response_model=Dict[str, Any])
async def update_enrollment_status(
    enrollment_id: str = Path(..., title="The ID of the enrollment to update"),
    update_data: EnrollmentStatusUpdate = Body(...),
    current_user: Dict[str, Any] = Depends(require_admin),
):
    """
    Update enrollment status (e.g., Pending -> Enrolled, or -> Withdrawn).
    """
    
    # Verify ID format
    if not ObjectId.is_valid(enrollment_id):
        raise HTTPException(status_code=400, detail="Invalid enrollment ID format")

    enrollment = await Enrollment.get(PydanticObjectId(enrollment_id))
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    # Change status
    previous_status = enrollment.status
    
    # Use atomic update to avoid overwriting other fields (grade, points, scores) with nulls
    await enrollment.update({"$set": {"status": update_data.status}})
    
    # Update local instance for subsequent logic
    enrollment.status = update_data.status

    # Create Alert for the student
    if enrollment.status == EnrollmentStatus.ENROLLED:
        alert_message = "You have been enrolled"
    elif enrollment.status == EnrollmentStatus.WITHDRAWN:
        reason_text = update_data.reason if update_data.reason else "unspecified reason"
        alert_message = f"Your enrollment is rejected because {reason_text}"
    else:
        reason_text = update_data.reason if update_data.reason else None
        alert_message = reason_text if reason_text else f"Your enrollment status has been updated to {enrollment.status}."

    await Alert(
        student_id=enrollment.student_id,
        message=alert_message
    ).insert()
    
    return {
        "message": alert_message,
        "enrollment_id": str(enrollment.id),
        "previous_status": previous_status,
        "new_status": enrollment.status,
        "reason": update_data.reason
    }
