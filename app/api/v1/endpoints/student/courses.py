from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict, Any, Optional
from beanie.operators import In
from app.api.v1.deps.auth import get_current_user
from app.models.user import User
from app.models.course import Course, CourseType
from app.models.enrollment import Enrollment, EnrollmentStatus
from pydantic import BaseModel

router = APIRouter(prefix="/student/courses", tags=["student-courses"])

class CourseResponse(BaseModel):
    tag: str
    credits: float
    title: str
    code: str
    instructor: Optional[str] = None
    location: Optional[str] = None

class DashboardResponse(BaseModel):
    semester_name: str
    total_credits: float
    max_credits: float = 18.0
    courses_count: int
    courses: List[CourseResponse]

@router.get("/current", response_model=DashboardResponse)
async def get_current_courses(current_user: Dict[str, Any] = Depends(get_current_user)):
    # Check if user has student_profile in the dict
    student_profile = current_user.get("student_profile")
    if not student_profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a student"
        )
    
    # Access current_year from the dict (student_profile is also a dict likely)
    # BEWARE: student_profile might be a dict or Pydantic model depending on how it was stored
    # Based on dep, user is just a raw dict from Mongo
    current_year = student_profile.get("current_year")
    
    # If using Enum in Python, we might get the raw string from DB, so handle both
    current_year_str = str(current_year)
    
    # 1. Find all courses that belong to this semester
    suitable_courses = await Course.find(
        {"semester.semester": current_year_str}
    ).to_list()

    # 2. Check for existing enrollments for this semester
    enrollments = await Enrollment.find(
        Enrollment.student_id == current_user["user_id"],
        Enrollment.semester_attend == current_year_str
    ).to_list()
    
    existing_course_ids = {e.course_id for e in enrollments}
    
    # 3. Auto-Enroll in missing courses (Idempotent fix)
    for course in suitable_courses:
            if course.course_code not in existing_course_ids:
                # IMPORTANT: Only include fields that are valid for the schema.
                # Do NOT include keys like 'grade': None if schema validation rejects null.
                # Beanie's insert() might handle this if model fields are Optional, 
                # but if it sends explicit null, Mongo schema fails.
                
                # Manual dict construction safer for strict schema validation
                # But we are using Beanie objects.
                
                new_enrollment = Enrollment(
                    student_id=current_user["user_id"],
                    course_id=course.course_code,
                    semester_attend=current_year_str,
                    status=EnrollmentStatus.ENROLLED
                    # grade, points, scores are allowed to be default (None)
                    # We rely on Beanie NOT sending them if they are Optional
                )
                
                # Force exclude fields that are None to prevent 'null type mismatch'
                # Beanie's insert() does not support exclude_none directly.
                # We need to manually remove None values or use a different method.
                # However, Pydantic's exclude_none is for export/dump.
                
                # Best hack for strict Mongo Schema + Beanie:
                # 1. Dump to dict without None
                # 2. Insert using raw driver access via .get_motor_collection()
                
                doc = new_enrollment.model_dump(by_alias=True, exclude_none=True)
                # Ensure _id is handled if auto-generated? Beanie handles it usually.
                # If we use insert_one, we bypass Beanie's state management partially but it works.
                
                # Check if we need to set id or if Mongo does it.
                # If we don't pass _id, Mongo creates ObjectId.
                # If our model expects string ID, we might have an issue if we don't generate it.
                # But Enrollment id is Optional[str], so ObjectId is "fine" but technically type mismatch in Python if we load it later as str without conversion.
                # Let's generate a string ID or let Mongo do its thing?
                # Usually better to let Beanie do it, but Beanie always sends fields.
                
                # ALTERNATIVE: Use skip_render=True on null fields in Model? Beanie doesn't have that easily.
                
                # Let's use the Raw Insert method for now to pass validation.
                await Enrollment.get_motor_collection().insert_one(doc)
                
                # Note: 'new_enrollment' object won't have the _id updated automatically from this raw insert
                # But we don't strictly need it for the response loop below (we just need course_id)
                
                enrollments.append(new_enrollment)
    
    # 4. Format response
    enrolled_course_codes = [e.course_id for e in enrollments]
    courses_data = await Course.find(
        In(Course.course_code, enrolled_course_codes)
    ).to_list()
    
    # Create a lookup for course data
    course_lookup = {c.course_code: c for c in courses_data}
    
    resp_courses = []
    total_credits = 0.0
    
    for enr in enrollments:
        course = course_lookup.get(enr.course_id)
        if course:
            resp_courses.append(CourseResponse(
                tag=course.type.upper(),
                credits=course.credits,
                title=course.title,
                code=course.course_code,
                instructor=course.instructor,
                location=course.room
            ))
            total_credits += course.credits
            
    return DashboardResponse(
        semester_name=str(current_year),
        total_credits=total_credits,
        courses_count=len(resp_courses),
        courses=resp_courses
    )
