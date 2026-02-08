from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict, Any, Optional, Union
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
    is_retake: bool = False

class DashboardResponse(BaseModel):
    semester_name: str
    total_credits: float
    max_credits: float = 18.0
    courses_count: int
    courses: List[CourseResponse]

class BulkDropRequest(BaseModel):
    course_codes: List[str]

class BulkDropResponse(BaseModel):
    success: bool
    message: str
    updated_total_credits: float
    updated_courses_count: int

class CourseDetailsResponse(BaseModel):
    course_code: str
    title: str
    instructor: Optional[str] = None
    credits: float
    # Helper handles both string or list, but response will be list ideally or match frontend
    # Frontend Types.ts says: string[] | string
    schedule: Union[List[str], str] = []
    room: Optional[str] = None
    description: Optional[str] = None
    syllabus: List[Dict[str, Any]] = []
    prerequisites: List[str] = []
    type: Optional[str] = None
    department: Optional[str] = None

@router.get("/detail/{course_code}", response_model=CourseDetailsResponse)
async def get_course_details(course_code: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    student_id = current_user.get("user_id")
    if not student_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    course = await Course.find_one(Course.course_code == course_code)
    if not course:
        raise HTTPException(status_code=404, detail=f"Course {course_code} not found")
    
    return course

@router.post("/bulk-drop", response_model=BulkDropResponse)
async def bulk_drop_courses(
    data: BulkDropRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    student_id = current_user.get("user_id")
    if not student_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    # 1. Update requested enrollments to DROPPED status
    # Instead of hard deleting, we soft delete so the system knows not to re-auto-enroll them
    print(f"DEBUG DROP REQUEST RECEIVED: Student={student_id}, Codes={data.course_codes}")
    
    # Try finding them first to prove they exist
    print(f"DEBUG DROP QUERY: student_id='{student_id}', codes={data.course_codes}")
    
    # Debug: List all enrollments for this student to see what matches
    all_student_enrollments = await Enrollment.find(Enrollment.student_id == student_id).to_list()
    print(f"DEBUG DROP: Student has {len(all_student_enrollments)} total enrollments.")
    if all_student_enrollments:
        print(f"DEBUG DROP: Sample enrollment course_ids: {[e.course_id for e in all_student_enrollments[:5]]}")

    existing_to_delete = await Enrollment.find(
        Enrollment.student_id == student_id,
        In(Enrollment.course_id, data.course_codes)
    ).to_list()
    print(f"DEBUG DROP: Found {len(existing_to_delete)} enrollments to drop.")

    update_result = await Enrollment.find(
        Enrollment.student_id == student_id,
        In(Enrollment.course_id, data.course_codes)
    ).update({"$set": {Enrollment.status: EnrollmentStatus.DROPPED}})
    
    print(f"DEBUG DROP: Student={student_id}, Codes={data.course_codes}")
    print(f"DEBUG DROP: Updated Count = {update_result.modified_count}")

    # 2. Recalculate remaining credits
    remaining_enrollments = await Enrollment.find(
        Enrollment.student_id == student_id,
        Enrollment.status == EnrollmentStatus.ENROLLED.value
    ).to_list()

    remaining_course_ids = [e.course_id for e in remaining_enrollments]
    
    # Fetch course details for credits
    remaining_courses = await Course.find(
        In(Course.course_code, remaining_course_ids)
    ).to_list()

    total_credits = sum(c.credits for c in remaining_courses)

    return BulkDropResponse(
        success=True,
        message=f"Successfully dropped {len(data.course_codes)} courses.",
        updated_total_credits=total_credits,
        updated_courses_count=len(remaining_courses)
    )

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
    
    # Helper to determine semester term (First vs Second)
    def get_term_parity(sem_str: str) -> str:
        if "First Sem" in sem_str:
            return "First Sem"
        elif "Second Sem" in sem_str:
            return "Second Sem"
        return "Unknown"

    current_term_parity = get_term_parity(current_year_str)

    # 1. Find all courses that belong to this semester (Standard Curriculum)
    suitable_courses = await Course.find(
        {"semester.semester": current_year_str}
    ).to_list()

    # 1.5 Find Retake Courses (Failed courses from previous matching semesters)
    # Logic: Status="Failed" AND Same Term Parity (Odd/Odd or Even/Even)
    # Changed to use Enrollments collection instead of academic_history embedded field
    
    print(f"DEBUG RETAKE: Checking for {current_user['user_id']} in {current_year_str} ({current_term_parity})")

    # Fetch all past failed enrollments for this student
    failed_enrollments = await Enrollment.find(
        Enrollment.student_id == current_user["user_id"],
        Enrollment.status == EnrollmentStatus.FAILED.value
    ).to_list()
    
    print(f"DEBUG RETAKE: Found {len(failed_enrollments)} failed courses.")

    retake_course_codes = []
    
    for record in failed_enrollments:
        # Check parity of the semester the course was failed in
        r_sem = record.semester_attend
        r_parity = get_term_parity(r_sem)
        print(f"DEBUG RETAKE: Checking {record.course_id} in {r_sem} ({r_parity}) vs Current ({current_term_parity})")
        
        if r_parity == current_term_parity:
             retake_course_codes.append(record.course_id)
             print(f"DEBUG RETAKE: Match! Adding {record.course_id}")

    # Fetch Ref objects for retakes
    retake_courses_objs = []
    if retake_course_codes:
        retake_courses_objs = await Course.find(
            In(Course.course_code, retake_course_codes)
        ).to_list()

    # 2. Check for existing enrollments for this semester
    enrollments = await Enrollment.find(
        Enrollment.student_id == current_user["user_id"],
        Enrollment.semester_attend == current_year_str
    ).to_list()
    
    existing_course_ids = {e.course_id for e in enrollments}
    
    # 3. Auto-Enroll Logic
    # Standard courses: Auto-enroll ONLY if zero enrollments exist (Fresh start).
    # Retake courses: ALWAYS auto-enroll if missing (Mandatory).
    
    courses_to_process_map = {}

    # 1. Add Standard Courses (Conditional)
    if not enrollments:
        for c in suitable_courses:
            courses_to_process_map[c.course_code] = c
    
    # 2. Add Retake Courses (Always)
    # This ensures that even if user has other enrollments, a missing Retake is forced in.
    for c in retake_courses_objs:
        courses_to_process_map[c.course_code] = c

    courses_to_process = list(courses_to_process_map.values())

    retake_codes_set = set(retake_course_codes)

    for course in courses_to_process:
            if course.course_code not in existing_course_ids:
                # Determine if this specific course is a retake
                is_retake_course = course.course_code in retake_codes_set

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
                    status=EnrollmentStatus.ENROLLED,
                    is_retake=is_retake_course
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
                existing_course_ids.add(course.course_code) # Prevent dupes if list logic changes
    
    # 4. Format response
    # Re-fetch everything to include newly created enrollments
    # Or just append? We appended to 'enrollments' list in loop.
    
    # SORTING LOGIC: Retakes first
    enrollments.sort(key=lambda x: x.is_retake, reverse=True)

    enrolled_course_codes = [e.course_id for e in enrollments]
    courses_data = await Course.find(
        In(Course.course_code, enrolled_course_codes)
    ).to_list()
    
    # Create a lookup for course data
    course_lookup = {c.course_code: c for c in courses_data}
    
    resp_courses = []
    total_credits = 0.0
    
    for enr in enrollments:
        # Skip dropped courses in valid list
        if enr.status == EnrollmentStatus.DROPPED or enr.status == EnrollmentStatus.DROPPED.value:
            continue

        course = course_lookup.get(enr.course_id)
        if course:
            # Add [Retake] tag to title if retake
            display_title = course.title
            if enr.is_retake:
                display_title = f"[Retake] {course.title}"

            resp_courses.append(CourseResponse(
                tag="RETAKE" if enr.is_retake else course.type.upper(),
                credits=course.credits,
                title=display_title,
                code=course.course_code,
                instructor=course.instructor,
                location=course.room,
                is_retake=enr.is_retake
            ))
            total_credits += course.credits
            
    return DashboardResponse(
        semester_name=str(current_year),
        total_credits=total_credits,
        courses_count=len(resp_courses),
        courses=resp_courses
    )
