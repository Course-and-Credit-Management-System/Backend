from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Dict, Any, Optional, Union
from beanie.operators import In, Or, RegEx
from app.api.v1.deps.auth import get_current_user
from app.models.user import User
from app.models.course import Course, CourseType
from app.models.enrollment import Enrollment, EnrollmentStatus
from pydantic import BaseModel
import uuid

router = APIRouter(prefix="/student/courses", tags=["student-courses"])

class CourseResponse(BaseModel):
    tag: str
    credits: float
    title: str
    code: str
    instructor: Optional[str] = None
    location: Optional[str] = None
    is_retake: bool = False

class CourseSearchItem(BaseModel):
    code: str
    title: str
    type: str
    credits: float
    desc: Optional[str] = None
    color: str
    status: str
    error: Optional[str] = None
    is_retake: bool
    schedule: Optional[str] = None
    message: Optional[str] = None
    enrollable: bool

class CourseSearchResponse(BaseModel):
    data: List[CourseSearchItem]
    meta: Dict[str, Any]

class EnrollmentRequest(BaseModel):
    selected_code: Union[str, List[str]]

class EnrollmentResponse(BaseModel):
    success: bool
    message: str
    credit_usage: Dict[str, Any]

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
    
    # DEBUG: Check what user current year is used to match
    print(f"DEBUG CURRENT: User Year={current_year_str}, Suitable Count={len(suitable_courses)}")
    
    # 1.5 Find Retake Courses (Failed courses from previous matching semesters)
    # Logic: Status="Failed" AND Same Term Parity (Odd/Odd or Even/Even)
    # Changed to use Enrollments collection instead of academic_history embedded field
    
    print(f"DEBUG RETAKE: Checking for {current_user['user_id']} in {current_year_str} ({current_term_parity})")

    # Fetch all past failed enrollments for this student
    failed_enrollments = await Enrollment.find(
        Enrollment.student_id == current_user['user_id'],
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
                new_enrollment = Enrollment(
                    student_id=current_user["user_id"],
                    course_id=course.course_code,
                    semester_attend=current_year_str,
                    status=EnrollmentStatus.ENROLLED,
                    is_retake=is_retake_course
                )
                
                # Best hack for strict Mongo Schema + Beanie:
                # 1. Dump to dict without None
                # 2. Insert using raw driver access via .get_motor_collection()
                doc = new_enrollment.model_dump(by_alias=True, exclude_none=True)
                await Enrollment.get_motor_collection().insert_one(doc)
                
                enrollments.append(new_enrollment)
                existing_course_ids.add(course.course_code)
    
    # 4. Format response
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


def get_course_color(course_type: str) -> str:
    # Basic mapping
    ct = course_type.lower()
    if "major" in ct: return "blue"
    if "core" in ct or "required" in ct: return "orange"
    if "elective" in ct: return "green"
    return "gray"

def time_to_minutes(t_str: str) -> int:
    try:
        t_str = t_str.strip()
        if ':' in t_str:
            h, m = map(int, t_str.split(':'))
            return h * 60 + m
    except:
        pass
    return 0

def parse_schedule_slots(schedule: Optional[List[str]]):
    slots = []
    if not schedule: return slots
    
    # Try different formats
    # Format 1: "Mon/Wed 10:00 - 11:30"
    # Format 2: "Monday 10:00-11:30"
    
    for s in schedule:
        if not s: continue
        s_clean = s.replace(" - ", "-").strip()
        
        # Split by spaces, trying to find the time part at the end
        parts = s_clean.split(" ")
        
        # Look for time range pattern like HH:MM-HH:MM
        time_part = None
        days_part = None
        
        # Iterate backwards to find time
        for i in range(len(parts) - 1, -1, -1):
            p = parts[i]
            if '-' in p and ':' in p:
                time_part = p
                # The rest before this is days
                days_part = " ".join(parts[:i])
                break
        
        if time_part and days_part:
            try:
                start_str, end_str = time_part.split('-')
                start_min = time_to_minutes(start_str)
                end_min = time_to_minutes(end_str)
                
                # Normalize days
                # Handle "Mon/Wed", "Mon, Wed", "Monday"
                # Simple normalization to 3 chars
                
                d_tokens = days_part.replace(',', ' ').replace('/', ' ').split()
                for d in d_tokens:
                    d = d.strip()
                    if d:
                        # normalize to first 3 chars title case if possible (Mon, Tue)
                        # This ensures "Monday" matches "Mon"
                        d_norm = d[:3].capitalize()
                        slots.append((d_norm, start_min, end_min))
            except:
                print(f"DEBUG: Failed to parse schedule item: {s}")
                pass
        else:
             # Fallback to my previous logic if spaces are messy "Mon 10:00 - 11:30"
             # My previous logic relied on -2, -1.
             # Let's try to extract time times using simple scan
             pass
             
    return slots

def has_schedule_conflict(slots1, slots2) -> bool:
    count = 0
    for d1, s1, e1 in slots1:
        for d2, s2, e2 in slots2:
            # Check day match (normalized)
            if d1 == d2:
                # Overlap logic: Start1 < End2 AND Start2 < End1
                if s1 < e2 and s2 < e1:
                    return True
    return False

@router.get("", response_model=CourseSearchResponse)
async def search_courses(
    sort: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    # 1. Fetch courses
    courses = await Course.find_all().to_list(length=None)

    # 2. Get Academic History & Current Year to check prerequisites & Parity
    # Fix: Correctly access academic_history from student_profile if available
    student_profile = current_user.get("student_profile") or {}
    academic_history = student_profile.get("academic_history", [])
    
    # Fallback/Legacy support if at root
    if not academic_history:
        academic_history = current_user.get("academic_history", [])
    
    user_current_year_str = str(student_profile.get("current_year", ""))
    
    user_parity = "Unknown"
    norm_user_year = user_current_year_str.lower()
    if "first sem" in norm_user_year or "firstsem" in norm_user_year or "1st sem" in norm_user_year: 
        user_parity = "First"
    elif "second sem" in norm_user_year or "secondsem" in norm_user_year or "2nd sem" in norm_user_year:
        user_parity = "Second"
    
    user_version = "Unknown"
    if "(new)" in norm_user_year or "new ." in norm_user_year: user_version = "new"
    elif "(old)" in norm_user_year or "old ." in norm_user_year: user_version = "old"

    # Identify passed courses
    passed_statuses = ["Passed", "Completed", "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "D"]
    passed_courses = {
        h["course_code"] for h in academic_history 
        if h.get("status") in passed_statuses or h.get("grade") in passed_statuses
    }

    # 3. Resolve Prerequisite Titles for error messages
    all_prereq_codes = set()
    for c in courses:
        if c.prerequisites:
            all_prereq_codes.update(c.prerequisites)
    
    prereq_titles = {}
    if all_prereq_codes:
        found_prereqs = await Course.find(In(Course.course_code, list(all_prereq_codes))).to_list()
        prereq_titles = {p.course_code: p.title for p in found_prereqs}

    # 4. active enrollments for schedule conflict check
    active_enrollments = await Enrollment.find(
        Enrollment.student_id == current_user.get("user_id"),
        In(Enrollment.status, [EnrollmentStatus.ENROLLED, EnrollmentStatus.PENDING]),
        Enrollment.semester_attend == user_current_year_str
    ).to_list()
    
    active_course_ids = {e.course_id for e in active_enrollments}
    course_map = {c.course_code: c for c in courses}
    
    busy_slots = []
    print(f"DEBUG_SCHED: Active courses: {list(active_course_ids)}")
    
    for cid in active_course_ids:
        if cid in course_map:
            c_obj = course_map[cid]
            if c_obj.schedule:
                parsed = parse_schedule_slots(c_obj.schedule)
                print(f"DEBUG_SCHED: Course {cid} schedule '{c_obj.schedule}' -> {parsed}")
                busy_slots.extend(parsed)

    response_data = []

    for course in courses:
        # A. Check Validity (Parity + Version)
        # Assuming course.semester is List[Dict] or List. 
        # If empty, ignore rules (assume universal).
        
        valid_context = True
        context_message = None
        
        if course.semester:
            has_matching_parity = False
            has_matching_version = False
            
            # Check against ALL definitions. If ANY fits, it's valid.
            for sem_def in course.semester:
                # Handle if sem_def is dict or string
                sem_name = ""
                if isinstance(sem_def, dict):
                    sem_name = str(sem_def.get("semester", ""))
                else:
                    sem_name = str(sem_def)

                norm_sem = sem_name.lower()
                c_parity = "Unknown"
                if "first sem" in norm_sem or "firstsem" in norm_sem or "1st sem" in norm_sem: c_parity = "First"
                elif "second sem" in norm_sem or "secondsem" in norm_sem or "2nd sem" in norm_sem: c_parity = "Second"
                
                c_version = "Unknown"
                if "(new)" in norm_sem or "new ." in norm_sem: c_version = "new"
                elif "(old)" in norm_sem or "old ." in norm_sem: c_version = "old"
                
                # Check Parity Match
                if c_parity == user_parity:
                    has_matching_parity = True
                    
                    # Check Version Match (Strict if tags exist)
                    is_compatible_version = True
                    if c_version == "new" and user_version != "new":
                        is_compatible_version = False
                    elif c_version == "old" and user_version != "old":
                         is_compatible_version = False
                    
                    if is_compatible_version:
                        has_matching_version = True
            
            # If no semester definitions matched parity
            if not has_matching_parity:
                valid_context = False
                context_message = "this course has been closed"
            
            # If parity matched, but version failed
            elif not has_matching_version:
                valid_context = False
                # Specific logic for exact message
                if user_version == "new":
                    context_message = "this course is for old student"
                else:
                    context_message = "this course is for new student"

        # B. Check prerequisites
        missing_prereqs = []
        for req in course.prerequisites:
            if req not in passed_courses:
                missing_prereqs.append(prereq_titles.get(req, req))
        
        # Check Schedule Conflict
        is_conflict = False
        if course.course_code not in active_course_ids:
            c_slots = parse_schedule_slots(course.schedule)
            if has_schedule_conflict(c_slots, busy_slots):
                # print(f"DEBUG_SCHED: Conflict detected for {course.course_code}. Slots: {c_slots} vs Busy: {busy_slots}")
                is_conflict = True
        
        error_msg = None
        status_str = "normal"
        
        # Priority Logic: Context > Prereq
        if not valid_context:
            status_str = "locked"
        elif missing_prereqs:
            status_str = "locked"
            error_msg = f"Missing Prerequisite: {', '.join(missing_prereqs)}"
        elif is_conflict:
             status_str = "locked"
        
        # C. Check if Retake
        already_taken = course.course_code in {h["course_code"] for h in academic_history}
        
        # Get schedule string
        sched = course.schedule[0] if course.schedule else None

        # Resolve type string
        c_type = course.type.value if hasattr(course.type, "value") else str(course.type)

        # Message Logic
        message_str = None
        if already_taken:
             message_str = "this course is already been taken"
        elif not valid_context:
             message_str = context_message
        elif is_conflict:
             message_str = "schedule conflicted"

        # Enrollable Logic
        # 1. Must be Normal status (unlocked context, prerequisites met)
        # 2. If already taken, MUST be explicitly 'Failed' to be enrollable (Retake). 
        #    (If status is missing or 'Passed', it is NOT enrollable).
        is_enrollable = False
        if status_str == "normal":
            if not already_taken:
                is_enrollable = True
            else:
                # Check specific status for retake capability
                # We know it is in history (already_taken=True)
                # If it is in passed_courses -> definitely False
                if course.course_code in passed_courses:
                    is_enrollable = False
                else:
                    # It is in history, but NOT passed.
                    # Check if explicitly Failed.
                    hist_entry = next((h for h in academic_history if h.get("course_code") == course.course_code), None)
                    if hist_entry:
                        stat = str(hist_entry.get("status", "")).lower()
                        grade = str(hist_entry.get("grade", "")).lower()
                        # Allow retry if Failed or F
                        if stat in ["failed", "fail", "f"] or grade in ["f", "fail"]:
                            is_enrollable = True
                        else:
                            # Ambiguous or 'Taken' matches user request for False
                            is_enrollable = False
                    else:
                        is_enrollable = False
        
        # Override status if not enrollable (for UI consistency)
        if not is_enrollable and status_str == "normal":
            status_str = "locked"
                        
        response_data.append(CourseSearchItem(
            code=course.course_code,
            title=course.title,
            type=c_type,
            credits=course.credits,
            desc=course.description,
            color=get_course_color(c_type),
            status=status_str,
            error=error_msg,
            is_retake=already_taken,
            schedule=sched,
            message=message_str,
            enrollable=is_enrollable
        ))
    
    if sort and sort.lower() == 'enrollable':
        # Filter to only include enrollable courses as requested
        response_data = [item for item in response_data if item.enrollable]
        # Optional: still sort alphabetically
        response_data.sort(key=lambda x: x.code)

    return CourseSearchResponse(
        data=response_data,
        meta={"total_count": len(response_data), "page": 1}
    )

@router.post("/enrollment", response_model=EnrollmentResponse)
async def finalize_enrollment(
    payload: EnrollmentRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    student_id = current_user["user_id"]
    
    # Get semester from student profile
    student_profile = current_user.get("student_profile") or {}
    current_semester = student_profile.get("current_year")
    
    if not current_semester:
         raise HTTPException(status_code=400, detail="Student has no current semester set")

    # Handle single string or list
    codes_to_enroll = []
    if isinstance(payload.selected_code, str):
        if "," in payload.selected_code:
            codes_to_enroll = [c.strip() for c in payload.selected_code.split(",")]
        else:
            codes_to_enroll = [payload.selected_code]
    elif isinstance(payload.selected_code, list):
        codes_to_enroll = payload.selected_code
    
    successful_enrollments = 0
    total_credits = 0
    
    for code in codes_to_enroll:
        # Check if course exists
        course = await Course.find_one(Course.course_code == code)
        if not course:
            continue
        
        total_credits += course.credits

        # Check existing enrollment
        existing = await Enrollment.find_one(
            Enrollment.student_id == student_id,
            Enrollment.course_id == code,
            Enrollment.semester_attend == current_semester
        )
        
        if not existing:
            # Determine if retake
            is_retake = False
            history = current_user.get("academic_history", [])
            for h in history:
                if h["course_code"] == code:
                    is_retake = True
                    break
            
            new_enr = Enrollment(
                student_id=student_id,
                course_id=code,
                semester_attend=str(current_semester),
                status=EnrollmentStatus.PENDING,
                is_retake=is_retake
            )
            # Use raw insert
            doc = new_enr.model_dump(by_alias=True, exclude_none=True)
            await Enrollment.get_motor_collection().insert_one(doc)
            successful_enrollments += 1

    return EnrollmentResponse(
        success=True,
        message="Enrollment request submitted successfully (Pending approval).",
        credit_usage={
            "total": total_credits, 
            "remaining_limit": 18 - total_credits # Max 18 assumption
        }
    )
