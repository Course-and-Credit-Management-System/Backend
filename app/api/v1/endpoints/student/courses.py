from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any, Optional, Union
from beanie.operators import In, Or, RegEx
from app.api.v1.deps.auth import get_current_user
from app.models.course import Course, CourseType
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.core.database import get_database
from app.services.enrollment_settings_service import (
    enforce_enrollment_window_or_403,
    get_effective_enrollment_settings_for_user,
)
from app.services.ai_chat_service import (
    ChatServiceError,
    MissingAIConfigError,
    RateLimitedAIError,
    chat_with_student_model,
)
from pydantic import BaseModel, Field
import asyncio
import json
import re
import uuid
import time
from datetime import datetime
from app.services.pdf_service import generate_current_courses_pdf

router = APIRouter(prefix="/student/courses", tags=["student-courses"])
_DROP_AI_CACHE_TTL_SECONDS = 120
_DROP_AI_COOLDOWN_SECONDS = 20
_drop_ai_plan_cache: Dict[str, Dict[str, Any]] = {}
_drop_ai_cooldown_until: Dict[str, float] = {}
_drop_ai_locks: Dict[str, asyncio.Lock] = {}

def _detect_semester_parity(value: Any) -> str:
    norm = str(value or "").strip().lower()
    # Check second-semester forms first to avoid matching "semester i" inside "semester ii".
    if (
        re.search(r"\bsecond\s*sem(?:ester)?\b", norm)
        or re.search(r"\b2nd\s*sem(?:ester)?\b", norm)
        or re.search(r"\bsem(?:ester)?\s*ii\b", norm)
    ):
        return "second"
    if (
        re.search(r"\bfirst\s*sem(?:ester)?\b", norm)
        or re.search(r"\b1st\s*sem(?:ester)?\b", norm)
        or re.search(r"\bsem(?:ester)?\s*i\b", norm)
    ):
        return "first"
    return "unknown"

def _detect_academic_year(value: Any) -> str:
    norm = str(value or "").strip().lower()
    if not norm:
        return "unknown"

    ordinal_match = re.search(r"\b([1-9])(?:st|nd|rd|th)\s*year\b", norm)
    if ordinal_match:
        return ordinal_match.group(1)

    word_map = {
        "first year": "1",
        "second year": "2",
        "third year": "3",
        "fourth year": "4",
        "fifth year": "5",
        "sixth year": "6",
    }
    for phrase, year_no in word_map.items():
        if phrase in norm:
            return year_no
    return "unknown"


def _detect_semester_version(value: Any) -> str:
    norm = str(value or "").strip().lower()
    if not norm:
        return "unknown"
    # Accept multiple notations: "(new)", "new .", "new •", "new -", "new ..."
    if re.search(r"\bnew\b", norm):
        return "new"
    if re.search(r"\bold\b", norm):
        return "old"
    return "unknown"


def _is_new_student(current_year: Any) -> bool:
    return _detect_semester_version(current_year) == "new"


def _normalize_track_token(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    compact = re.sub(r"[^a-z]", "", raw)
    if compact in {"cs", "computerscience"}:
        return "cs"
    if compact in {"ct", "computertechnology"}:
        return "ct"
    return compact


def _parse_semester_label(value: Any) -> tuple[str, str, str]:
    """
    Flexible parser for semester labels with dots, bullets, commas, or parentheses.
    Returns: (version, year, parity), using "unknown" for missing parts.
    """
    raw = str(value or "").strip()
    if not raw:
        return ("unknown", "unknown", "unknown")

    norm = raw.lower().replace("â€¢", "•")
    version = _detect_semester_version(norm)
    year = _detect_academic_year(norm)
    parity = _detect_semester_parity(norm)
    return (version, year, parity)

def _is_program_eligible_for_student(
    *,
    is_new_student: bool,
    selected_major: str,
    selected_track: str,
    course_major: str,
    course_track: str,
) -> bool:
    student_major = str(selected_major or "").strip().lower()
    student_track = _normalize_track_token(selected_track)
    c_major = str(course_major or "").strip().lower()
    c_track = _normalize_track_token(course_track)
    is_neutral_course = not c_major and not c_track

    has_major = bool(student_major)
    has_track = bool(student_track)

    # Neutral courses are not restricted by major/track program matching.
    if is_neutral_course:
        return True

    if is_new_student:
        # New student ignores track completely.
        if has_major:
            # New + major => strict major match only.
            return c_major == student_major
        # New + no major => current logic (no program restriction).
        return True

    # Old student rules
    if has_track and not has_major:
        # Old + track only => same track, any major.
        return c_track == student_track
    if has_track and has_major:
        # Old + track + major => both must match.
        return c_track == student_track and c_major == student_major
    if not has_major and not has_track:
        # Old + neither => current logic (no program restriction).
        return True

    return True


def _course_matches_current_context(
    course: Any,
    current_year: Any,
    *,
    strict_year: bool = False,
) -> bool:
    """A course is valid if any semester entry matches student's current year context."""
    semester_defs = getattr(course, "semester", None) or []
    if not semester_defs:
        return False

    user_version, user_year, user_parity = _parse_semester_label(current_year)
    if "unknown" in {user_version, user_parity}:
        return False

    for sem_def in semester_defs:
        if isinstance(sem_def, dict):
            sem_name = sem_def.get("semester", "")
        else:
            sem_name = sem_def
        sem_version, sem_year, sem_parity = _parse_semester_label(sem_name)
        if strict_year:
            if "unknown" in {user_year, sem_year}:
                continue
            if sem_version == user_version and sem_year == user_year and sem_parity == user_parity:
                return True
        else:
            # Relaxed mode: year ignored.
            if sem_version == user_version and sem_parity == user_parity:
                return True

    return False


async def _get_col(db, names: List[str]):
    cols = await db.list_collection_names()
    for n in names:
        if n in cols:
            return db[n]
    return db[names[0]]

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
    semester: List[str] = Field(default_factory=list)
    track: Optional[str] = None
    sort_index: int = 99
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


class EnrollmentAssistanceRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)


class EnrollmentAssistanceItem(BaseModel):
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
    reason: str


class EnrollmentAssistanceResponse(BaseModel):
    data: List[EnrollmentAssistanceItem]
    meta: Dict[str, Any]


class DropRecommendationItem(BaseModel):
    code: str
    title: str
    type: str
    credits: float
    reason: str


class DropRecommendationResponse(BaseModel):
    exceeds_limit: bool
    message: str
    credit_limit: float
    current_total_credits: float
    credits_to_drop: float
    elective: Optional[DropRecommendationItem] = None
    others: List[DropRecommendationItem] = Field(default_factory=list)

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
    is_new_student = _is_new_student(current_year_str)
    effective_settings = await get_effective_enrollment_settings_for_user(current_user=current_user)

    progress_doc = current_user.get("students_progress") or {}
    if not progress_doc:
        db = await get_database()
        progress_col = await _get_col(db, ["students_progress", "StudentsProgress"])
        progress_doc = await progress_col.find_one({"student_id": current_user["user_id"]}) or {}
    selected_major = str(progress_doc.get("selected_major") or "").strip()
    selected_track = str(progress_doc.get("selected_track") or "").strip()

    passed_codes = await _get_passed_course_codes(
        current_user=current_user,
        student_id=str(current_user["user_id"]),
    )

    def _build_progress_filter() -> Dict[str, Any]:
        neutral_course_filter: Dict[str, Any] = {
            "$or": [{"major": {"$exists": False}}, {"major": None}, {"major": ""}]
        }

        # New students ignore track constraints.
        if is_new_student:
            if selected_major:
                # New + major: strict major match.
                return {"major": selected_major}
            # New + no major: only neutral courses.
            return neutral_course_filter

        # Old students:
        # - track only => same track (major can be anything)
        # - major + track => same major+track
        # - major only => semester-only
        # - neither => only neutral courses
        if selected_major and selected_track:
            return {"major": selected_major, "track": selected_track}
        if selected_track:
            return {"track": selected_track}
        if not selected_major and not selected_track:
            return neutral_course_filter
        return {}

    def _and_filters(*parts: Dict[str, Any]) -> Dict[str, Any]:
        filtered = [p for p in parts if p]
        if not filtered:
            return {}
        if len(filtered) == 1:
            return filtered[0]
        return {"$and": filtered}
    
    # Helper to determine semester term (First vs Second)
    def get_term_parity(sem_str: str) -> str:
        parity = _detect_semester_parity(sem_str)
        if parity == "first":
            return "First Sem"
        if parity == "second":
            return "Second Sem"
        return "Unknown"

    current_term_parity = get_term_parity(current_year_str)

    # 1. Find semester-compatible courses, then apply major/track and "not already passed".
    progress_filter = _build_progress_filter()
    base_course_query: Dict[str, Any] = _and_filters(progress_filter)
    semester_courses = await Course.find(base_course_query).to_list()
    suitable_courses = [
        c for c in semester_courses
        if c.course_code not in passed_codes and _course_matches_current_context(
            c,
            current_year_str,
            strict_year=True,
        )
    ]
    
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
        retake_query: Dict[str, Any] = {
            "course_code": {"$in": retake_course_codes},
        }
        retake_query = _and_filters(
            retake_query,
            progress_filter,
        )
        retake_courses_raw = await Course.find(retake_query).to_list()
        retake_courses_objs = [
            c for c in retake_courses_raw
            if c.course_code not in passed_codes and _course_matches_current_context(
                c,
                current_year_str,
                strict_year=True,
            )
        ]

    # 2. Check for existing enrollments for this semester
    enrollments = await Enrollment.find(
        Enrollment.student_id == current_user["user_id"],
        Enrollment.semester_attend == current_year_str
    ).to_list()

    existing_course_ids_all = {e.course_id for e in enrollments}
    existing_course_ids = set()
    if enrollments:
        enrollment_codes = [e.course_id for e in enrollments]
        eligible_codes = {c.course_code for c in suitable_courses}
        existing_course_ids = {
            code for code in enrollment_codes
            if code in eligible_codes and code not in passed_codes
        }
    
    # 3. Auto-Enroll Logic
    # Refresh rule:
    #  - Count current-semester enrollments for this student.
    #  - Count eligible same-semester courses.
    #  - If counts are equal -> skip standard auto-enroll.
    #  - If counts differ -> auto-enroll missing standard courses.
    # Retake courses remain mandatory and are still enforced.
    
    courses_to_process_map = {}

    existing_active_codes = {
        str(e.course_id or "").strip()
        for e in enrollments
        if (e.status != EnrollmentStatus.DROPPED and e.status != EnrollmentStatus.DROPPED.value)
        and str(e.course_id or "").strip()
    }
    eligible_standard_codes = {str(c.course_code or "").strip() for c in suitable_courses if str(c.course_code or "").strip()}

    needs_standard_auto_enroll = len(existing_active_codes) != len(eligible_standard_codes)
    print(
        f"DEBUG AUTO-ENROLL: enrolled_count={len(existing_active_codes)} "
        f"eligible_semester_count={len(eligible_standard_codes)} "
        f"needs_enroll={needs_standard_auto_enroll}"
    )

    # 1. Add Standard Courses only when count mismatch.
    if needs_standard_auto_enroll:
        for c in suitable_courses:
            courses_to_process_map[c.course_code] = c
    
    # 2. Add Retake Courses (Always)
    # This ensures that even if user has other enrollments, a missing Retake is forced in.
    for c in retake_courses_objs:
        courses_to_process_map[c.course_code] = c

    courses_to_process = list(courses_to_process_map.values())

    retake_codes_set = set(retake_course_codes)

    for course in courses_to_process:
            if course.course_code not in existing_course_ids_all:
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
                existing_course_ids_all.add(course.course_code)
                existing_course_ids.add(course.course_code)
    
    # 4. Format response
    enrollments.sort(key=lambda x: x.is_retake, reverse=True)

    enrolled_course_codes = [
        str(e.course_id or "").strip()
        for e in enrollments
        if str(e.course_id or "").strip()
    ]
    course_lookup = {}
    if enrolled_course_codes:
        # Important: current courses should always include courses already enrolled
        # for this semester, even if they no longer match progress/context filters.
        courses_data = await Course.find({"course_code": {"$in": enrolled_course_codes}}).to_list()
        course_lookup = {str(c.course_code or "").strip(): c for c in courses_data}
    
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
        max_credits=float(effective_settings.max_credits),
        courses_count=len(resp_courses),
        courses=resp_courses
    )


@router.get("/current/pdf")
async def download_current_courses_pdf(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Generate and download current course schedule as a professional PDF."""
    schedule = await get_current_courses(current_user)
    schedule_payload = schedule.model_dump() if hasattr(schedule, "model_dump") else dict(schedule)
    student_profile = current_user.get("student_profile") or {}

    pdf_buffer = generate_current_courses_pdf(
        {
            "student": {
                "name": current_user.get("name") or "",
                "user_id": current_user.get("user_id") or "",
                "current_year": student_profile.get("current_year") or "",
            },
            "schedule": schedule_payload,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )

    headers = {
        "Content-Disposition": 'attachment; filename="current_course_schedule.pdf"'
    }
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)


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

def parse_schedule_slots(schedule: Optional[Union[List[str], str]]):
    slots = []
    if not schedule:
        return slots

    items = schedule if isinstance(schedule, list) else [schedule]
    day_map = {
        "mon": "Mon", "monday": "Mon",
        "tue": "Tue", "tues": "Tue", "tuesday": "Tue",
        "wed": "Wed", "wednesday": "Wed",
        "thu": "Thu", "thur": "Thu", "thurs": "Thu", "thursday": "Thu",
        "fri": "Fri", "friday": "Fri",
        "sat": "Sat", "saturday": "Sat",
        "sun": "Sun", "sunday": "Sun",
    }

    for raw in items:
        s = str(raw or "").strip()
        if not s:
            continue

        s_clean = s.replace("–", "-").replace("—", "-").replace(" - ", "-")
        time_match = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", s_clean)
        if not time_match:
            continue

        start_min = time_to_minutes(time_match.group(1))
        end_min = time_to_minutes(time_match.group(2))
        if start_min <= 0 or end_min <= 0 or start_min >= end_min:
            continue

        days_part = s_clean[:time_match.start()]
        day_tokens = re.findall(
            r"\b(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:r|rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
            days_part.lower(),
        )
        for token in day_tokens:
            day_norm = day_map.get(token)
            if day_norm:
                slots.append((day_norm, start_min, end_min))

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


def _extract_ai_recommendations(answer_text: str) -> List[Dict[str, str]]:
    raw = (answer_text or "").strip()
    if not raw:
        return []

    parsed: Any = None
    try:
        parsed = json.loads(raw)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None

    if not isinstance(parsed, dict):
        return []

    items = parsed.get("recommendations")
    if not isinstance(items, list):
        return []

    normalized: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if code and reason:
            normalized.append({"code": code, "reason": reason[:120]})
    return normalized


def _extract_ai_drop_recommendation(answer_text: str) -> Dict[str, Any]:
    raw = (answer_text or "").strip()
    if not raw:
        return {}

    parsed: Any = None
    try:
        parsed = json.loads(raw)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None

    if not isinstance(parsed, dict):
        return {}
    return parsed


def _is_elective_course(course: CourseResponse) -> bool:
    return "elective" in str(course.tag or "").lower()


def _is_retake_course(course: CourseResponse) -> bool:
    if bool(course.is_retake):
        return True
    if "retake" in str(course.tag or "").lower():
        return True
    return str(course.title or "").strip().lower().startswith("[retake]")


def _fallback_drop_plan(
    current_courses: List[CourseResponse],
    excess_credits: float,
) -> Dict[str, Any]:
    available_map = {c.code: c for c in current_courses}
    droppable_courses = [c for c in current_courses if not _is_retake_course(c)]
    elective_courses = [c for c in droppable_courses if _is_elective_course(c)]
    non_elective_courses = [c for c in droppable_courses if not _is_elective_course(c)]

    selected: List[DropRecommendationItem] = []

    if len(elective_courses) > 1:
        sorted_electives = sorted(elective_courses, key=lambda c: c.credits, reverse=True)
        for e in sorted_electives[1:]:
            selected.append(
                DropRecommendationItem(
                    code=e.code,
                    title=e.title,
                    type=e.tag,
                    credits=e.credits,
                    reason="Only one elective should remain this semester.",
                )
            )

    dropped_credits = sum(item.credits for item in selected)
    remaining_needed = max(0.0, excess_credits - dropped_credits)
    if remaining_needed > 0:
        for c in sorted(non_elective_courses, key=lambda x: x.credits, reverse=True):
            selected.append(
                DropRecommendationItem(
                    code=c.code,
                    title=c.title,
                    type=c.tag,
                    credits=c.credits,
                    reason="Dropping this helps reduce your total credits quickly.",
                )
            )
            remaining_needed = max(0.0, remaining_needed - c.credits)
            if remaining_needed <= 0:
                break

    unique: Dict[str, DropRecommendationItem] = {}
    for item in selected:
        if item.code in available_map and item.code not in unique:
            unique[item.code] = item

    ordered = list(unique.values())
    elective = next((x for x in ordered if _is_elective_course(available_map[x.code])), None)
    others = [x for x in ordered if elective is None or x.code != elective.code]
    return {"elective": elective, "others": others}


def _build_drop_ai_cache_key(
    student_id: str,
    current_courses: List[CourseResponse],
    total_credits: float,
    credit_limit: float,
) -> str:
    signature_parts = [
        f"{c.code}:{c.credits}:{int(bool(c.is_retake))}:{c.tag}"
        for c in current_courses
    ]
    signature_parts.sort()
    signature = "|".join(signature_parts)
    return f"{student_id}:{total_credits}:{credit_limit}:{signature}"


def _get_drop_ai_lock(student_id: str) -> asyncio.Lock:
    lock = _drop_ai_locks.get(student_id)
    if lock is None:
        lock = asyncio.Lock()
        _drop_ai_locks[student_id] = lock
    return lock


def _prune_drop_ai_cache(now_ts: float) -> None:
    expired_keys = [
        key for key, value in _drop_ai_plan_cache.items()
        if float(value.get("expires_at", 0.0)) <= now_ts
    ]
    for key in expired_keys:
        _drop_ai_plan_cache.pop(key, None)


def _cache_drop_ai_plan(cache_key: str, now_ts: float, plan: Dict[str, Any]) -> None:
    _drop_ai_plan_cache[cache_key] = {
        "expires_at": now_ts + _DROP_AI_CACHE_TTL_SECONDS,
        "plan": plan,
    }


async def _get_passed_course_codes(current_user: Dict[str, Any], student_id: str) -> set[str]:
    student_profile = current_user.get("student_profile") or {}
    academic_history = student_profile.get("academic_history", []) or current_user.get("academic_history", [])

    passed_statuses = {"passed", "completed"}
    passing_grades = {"a+", "a", "a-", "b+", "b", "b-", "c+", "c", "d"}

    passed_codes: set[str] = set()
    for item in academic_history:
        course_code = str(item.get("course_code") or item.get("course_id") or "").strip()
        status_value = str(item.get("status") or "").strip().lower()
        grade_value = str(item.get("grade") or "").strip().lower()
        if course_code and (status_value in passed_statuses or grade_value in passing_grades):
            passed_codes.add(course_code)

    db_passed = await Enrollment.find(
        Enrollment.student_id == student_id,
        In(Enrollment.status, [EnrollmentStatus.PASSED, EnrollmentStatus.COMPLETED]),
    ).to_list()
    for enrollment in db_passed:
        if enrollment.course_id:
            passed_codes.add(str(enrollment.course_id))

    return passed_codes

@router.get("", response_model=CourseSearchResponse)
async def search_courses(
    sort: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    sort_tokens = {
        token.strip().lower()
        for token in re.split(r"[,\|]", (sort or ""))
        if token and token.strip()
    }
    wants_enrollable_only = "enrollable" in sort_tokens or "enrollment" in sort_tokens
    wants_major_only = (
        "major" in sort_tokens
        or "type:major" in sort_tokens
        or "course_type:major" in sort_tokens
    )
    wants_cs_only = "cs" in sort_tokens or "track:cs" in sort_tokens
    wants_ct_only = "ct" in sort_tokens or "track:ct" in sort_tokens
    has_supported_filters = wants_cs_only or wants_ct_only or wants_major_only or wants_enrollable_only

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
    
    is_new_student = _is_new_student(user_current_year_str)

    progress_doc = current_user.get("students_progress") or {}
    if not isinstance(progress_doc, dict):
        progress_doc = {}
    if not progress_doc:
        db = await get_database()
        progress_col = await _get_col(db, ["students_progress", "StudentsProgress"])
        user_id_value = str(current_user.get("user_id") or "").strip()
        email_value = str(current_user.get("email") or "").strip()
        progress_matchers = []
        if user_id_value:
            progress_matchers.extend(
                [
                    {"student_id": user_id_value},
                    {"user_id": user_id_value},
                    {"student_user_id": user_id_value},
                    {"studentId": user_id_value},
                    {"userId": user_id_value},
                ]
            )
        if email_value:
            progress_matchers.append({"email": email_value})
        progress_doc = await progress_col.find_one({"$or": progress_matchers}) if progress_matchers else {}
        progress_doc = progress_doc or {}
    selected_major = str(
        progress_doc.get("selected_major")
        or progress_doc.get("major")
        or current_user.get("selected_major")
        or current_user.get("major")
        or ""
    ).strip()
    selected_track = str(
        progress_doc.get("selected_track")
        or progress_doc.get("track")
        or progress_doc.get("selectedTrack")
        or current_user.get("selected_track")
        or current_user.get("track")
        or ""
    ).strip()
    # Course major/track may not be part of the typed model in all datasets.
    course_meta_map: Dict[str, Dict[str, str]] = {}
    if selected_major or selected_track or wants_cs_only or wants_ct_only:
        db = await get_database()
        courses_col = await _get_col(db, ["Courses", "courses"])
        raw_courses = await courses_col.find({}, {"course_code": 1, "major": 1, "track": 1}).to_list(None)
        course_meta_map = {
            str(doc.get("course_code") or "").strip(): {
                "major": str(doc.get("major") or "").strip(),
                "track": str(doc.get("track") or "").strip(),
            }
            for doc in raw_courses
            if doc.get("course_code")
        }

    # Identify passed courses
    passed_statuses = ["Passed", "Completed", "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "D"]
    passed_courses = {
        h["course_code"] for h in academic_history 
        if h.get("status") in passed_statuses or h.get("grade") in passed_statuses
    }

    history_course_codes = {
        str(h.get("course_code") or h.get("course_id") or "").strip()
        for h in academic_history
        if (h.get("course_code") or h.get("course_id"))
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
    
    active_course_ids = {str(e.course_id or "").strip() for e in active_enrollments if e.course_id}
    enrolled_course_ids = set()
    pending_course_ids = set()
    for e in active_enrollments:
        status_val = getattr(e, "status", "")
        if hasattr(status_val, "value"):
            status_text = str(getattr(status_val, "value", "")).strip().lower()
        else:
            status_text = str(status_val or "").strip().lower()
            status_text = status_text.split(".")[-1]
        if status_text == "enrolled":
            code = str(getattr(e, "course_id", "") or "").strip()
            if code:
                enrolled_course_ids.add(code)
        elif status_text == "pending":
            code = str(getattr(e, "course_id", "") or "").strip()
            if code:
                pending_course_ids.add(code)
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
        semester_values = []
        for sem_def in (course.semester or []):
            if isinstance(sem_def, dict):
                sem_name = str(sem_def.get("semester") or "").strip()
            else:
                sem_name = str(sem_def or "").strip()
            if sem_name:
                semester_values.append(sem_name)

        # Skip courses that have no semester definitions at all.
        # They should not be considered enrollable nor shown in normal search.
        if not semester_values:
            continue

        # A. Check validity against current student semester context.
        valid_context = True
        context_message = None
        if not _course_matches_current_context(course, user_current_year_str):
            valid_context = False
            context_message = "this course has been closed"
            user_version, _, _ = _parse_semester_label(user_current_year_str)
            course_versions = set()
            for sem_name in semester_values:
                sem_version, _, _ = _parse_semester_label(sem_name)
                if sem_version in {"old", "new"}:
                    course_versions.add(sem_version)
            if user_version == "new" and course_versions and course_versions <= {"old"}:
                context_message = "this course is for old student."
            elif user_version == "old" and course_versions and course_versions <= {"new"}:
                context_message = "this course is for new student."

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

        # Resolve type and major/track compatibility
        c_type = course.type.value if hasattr(course.type, "value") else str(course.type)
        course_meta = course_meta_map.get(course.course_code, {})
        course_major = str(
            course_meta.get("major")
            or getattr(course, "major", "")
            or ""
        ).strip()
        course_track = str(
            course_meta.get("track")
            or getattr(course, "track", "")
            or ""
        ).strip()
        course_track_norm = _normalize_track_token(course_track)
        track_sort_priority = {"cs": 0, "ct": 1}
        sort_index = track_sort_priority.get(course_track_norm, 99)

        is_program_eligible = _is_program_eligible_for_student(
            is_new_student=is_new_student,
            selected_major=selected_major,
            selected_track=selected_track,
            course_major=course_major,
            course_track=course_track,
        )

        has_program_mismatch = not is_program_eligible
        course_code_str = str(course.course_code or "").strip()
        is_currently_enrolled = course_code_str in enrolled_course_ids
        is_pending = course_code_str in pending_course_ids
        
        error_msg = None
        status_str = "normal"
        
        # Priority Logic: Context > Prereq
        if is_currently_enrolled or is_pending:
            status_str = "locked"
        elif not valid_context:
            status_str = "locked"
        elif missing_prereqs:
            status_str = "locked"
            error_msg = f"Missing Prerequisite: {', '.join(missing_prereqs)}"
        elif has_program_mismatch:
            status_str = "locked"
        elif is_conflict:
             status_str = "locked"
        
        # C. Course present in academic history is treated as completed/non-enrollable
        already_taken = course.course_code in history_course_codes
        
        # Get schedule string
        sched = course.schedule[0] if course.schedule else None

        # Message Logic
        message_str = None
        if is_currently_enrolled:
             message_str = "you are currently enrolling."
        elif is_pending:
             message_str = "your enrollment is pending approval."
        elif already_taken:
             message_str = "this course have been completed."
        elif not valid_context:
             message_str = context_message
        elif has_program_mismatch:
             message_str = "this course is not for your major/track"
        elif is_conflict:
             message_str = "schedule conflicted"

        # Enrollable Logic
        # Must pass all checks and must not be present in academic history.
        is_enrollable = status_str == "normal" and not already_taken
        
        # Override status if not enrollable (for UI consistency)
        if not is_enrollable and status_str == "normal":
            status_str = "locked"
                        
        response_data.append(CourseSearchItem(
            code=course.course_code,
            title=course.title,
            type=c_type,
            credits=course.credits,
            semester=semester_values,
            track=(course_track or (course_track_norm.upper() if course_track_norm else None)),
            sort_index=sort_index,
            desc=course.description,
            color=get_course_color(c_type),
            status=status_str,
            error=error_msg,
            is_retake=already_taken,
            schedule=sched,
            message=message_str,
            enrollable=is_enrollable
        ))
    
    if wants_cs_only:
        response_data = [item for item in response_data if _normalize_track_token(item.track) == "cs"]

    if wants_ct_only:
        response_data = [item for item in response_data if _normalize_track_token(item.track) == "ct"]

    if wants_major_only:
        response_data = [item for item in response_data if item.type.lower() == "major"]

    if wants_enrollable_only:
        # Filter to only include enrollable courses as requested
        response_data = [item for item in response_data if item.enrollable]

    if has_supported_filters:
        # Keep deterministic output for filtered views with track ordering (CS, CT, then others).
        response_data.sort(key=lambda x: (x.sort_index, x.code))

    return CourseSearchResponse(
        data=response_data,
        meta={"total_count": len(response_data), "page": 1}
    )


@router.post("/enrollment-assistance", response_model=EnrollmentAssistanceResponse)
async def course_enrollment_assistance(
    payload: EnrollmentAssistanceRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    role = (current_user.get("role") or "").lower()
    if role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="student role required",
        )

    enrollable_result = await search_courses(sort="enrollable", current_user=current_user)
    enrollable_items = enrollable_result.data
    if not enrollable_items:
        return EnrollmentAssistanceResponse(
            data=[],
            meta={"total_count": 0, "page": 1},
        )

    enrollable_map = {c.code: c for c in enrollable_items}

    candidates_for_ai = [
        {
            "code": c.code,
            "title": c.title,
            "credits": c.credits,
            "type": c.type,
            "desc": c.desc,
            "schedule": c.schedule,
        }
        for c in enrollable_items
    ]

    ai_prompt = (
        "Recommend enrollable courses for this student.\n"
        "Only choose from CANDIDATE_COURSES.\n"
        "Prefer courses related to STUDENT_MESSAGE.\n"
        "Return valid JSON only:\n"
        '{"recommendations":[{"code":"COURSE_CODE","reason":"short reason"}]}\n'
        "Rules:\n"
        "- max 5 courses\n"
        "- reason must be short (max 12 words)\n"
        "- do not include courses outside CANDIDATE_COURSES\n\n"
        f"STUDENT_MESSAGE: {payload.message}\n"
        f"CANDIDATE_COURSES: {json.dumps(candidates_for_ai, ensure_ascii=False)}"
    )

    try:
        ai_answer, _ = await chat_with_student_model(
            question=ai_prompt,
            current_user=current_user,
            history=None,
            mode="course_selection",
        )
    except MissingAIConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except RateLimitedAIError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except ChatServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while generating course assistance.",
        ) from exc

    ai_recs = _extract_ai_recommendations(ai_answer)
    seen_codes = set()
    recommendations: List[EnrollmentAssistanceItem] = []

    for rec in ai_recs:
        code = rec["code"]
        if code in seen_codes or code not in enrollable_map:
            continue
        course = enrollable_map[code]
        recommendations.append(
            EnrollmentAssistanceItem(
                code=course.code,
                title=course.title,
                type=course.type,
                credits=course.credits,
                desc=course.desc,
                color=course.color,
                status=course.status,
                error=course.error,
                is_retake=course.is_retake,
                schedule=course.schedule,
                message=course.message,
                enrollable=course.enrollable,
                reason=rec["reason"],
            )
        )
        seen_codes.add(code)
        if len(recommendations) >= 5:
            break

    if not recommendations:
        fallback_codes = [c.code for c in enrollable_items[:3]]
        for code in fallback_codes:
            course = enrollable_map[code]
            recommendations.append(
                EnrollmentAssistanceItem(
                    code=course.code,
                    title=course.title,
                    type=course.type,
                    credits=course.credits,
                    desc=course.desc,
                    color=course.color,
                    status=course.status,
                    error=course.error,
                    is_retake=course.is_retake,
                    schedule=course.schedule,
                    message=course.message,
                    enrollable=course.enrollable,
                    reason="Fits your current enrollable course options.",
                )
            )

    return EnrollmentAssistanceResponse(
        data=recommendations,
        meta={"total_count": len(recommendations), "page": 1},
    )


@router.get("/drop-recommendation", response_model=DropRecommendationResponse)
async def course_drop_recommendation(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    role = (current_user.get("role") or "").lower()
    if role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="student role required",
        )

    current_data = await get_current_courses(current_user=current_user)
    current_courses = current_data.courses
    total_credits = float(current_data.total_credits)
    credit_limit = float(current_data.max_credits)
    excess_credits = max(0.0, total_credits - credit_limit)

    if excess_credits <= 0:
        return DropRecommendationResponse(
            exceeds_limit=False,
            message=f"Your current enrollment is within the {credit_limit:g}-credit limit.",
            credit_limit=credit_limit,
            current_total_credits=total_credits,
            credits_to_drop=0.0,
            elective=None,
            others=[],
        )

    candidates = [
        {
            "code": c.code,
            "title": c.title,
            "type": c.tag,
            "credits": c.credits,
            "is_retake": c.is_retake,
        }
        for c in current_courses
    ]
    elective_codes = [c.code for c in current_courses if _is_elective_course(c)]
    non_droppable_retake_codes = [c.code for c in current_courses if _is_retake_course(c)]

    ai_prompt = (
        "You are an academic trade-off assistant.\n"
        "Student is over the semester credit limit and needs course drop recommendations.\n"
        "Return VALID JSON only with this exact shape:\n"
        '{"elective":{"code":"COURSE_CODE","reason":"short reason"},"others":[{"code":"COURSE_CODE","reason":"short reason"}]}\n'
        "Rules:\n"
        "- NEVER suggest dropping any retake course (is_retake=true).\n"
        "- The student must keep at most ONE elective course.\n"
        "- Minimize number of dropped courses.\n"
        "- If removing one course is enough to be <= limit, do not suggest extra drops.\n"
        "- Pick from CANDIDATES only.\n"
        "- Keep each reason short (max 16 words).\n\n"
        f"CREDIT_LIMIT: {credit_limit}\n"
        f"CURRENT_TOTAL_CREDITS: {total_credits}\n"
        f"EXCESS_CREDITS: {excess_credits}\n"
        f"ELECTIVE_CODES: {json.dumps(elective_codes, ensure_ascii=False)}\n"
        f"NON_DROPPABLE_RETAKE_CODES: {json.dumps(non_droppable_retake_codes, ensure_ascii=False)}\n"
        f"CANDIDATES: {json.dumps(candidates, ensure_ascii=False)}"
    )

    ai_plan: Dict[str, Any] = {}
    ai_unavailable_reason: Optional[str] = None

    student_id = str(current_user.get("user_id") or "")
    cache_key = _build_drop_ai_cache_key(
        student_id=student_id,
        current_courses=current_courses,
        total_credits=total_credits,
        credit_limit=credit_limit,
    )
    now_ts = time.time()
    _prune_drop_ai_cache(now_ts)
    cached = _drop_ai_plan_cache.get(cache_key)
    if cached and float(cached.get("expires_at", 0.0)) > now_ts:
        cached_plan = cached.get("plan")
        if isinstance(cached_plan, dict):
            ai_plan = cached_plan

    in_cooldown = float(_drop_ai_cooldown_until.get(student_id, 0.0)) > now_ts
    if not ai_plan and in_cooldown:
        ai_unavailable_reason = "AI temporary cooldown due to recent rate limiting."

    if not ai_plan and not in_cooldown:
        async with _get_drop_ai_lock(student_id):
            now_ts = time.time()
            _prune_drop_ai_cache(now_ts)
            cached = _drop_ai_plan_cache.get(cache_key)
            if cached and float(cached.get("expires_at", 0.0)) > now_ts:
                cached_plan = cached.get("plan")
                if isinstance(cached_plan, dict):
                    ai_plan = cached_plan

            in_cooldown = float(_drop_ai_cooldown_until.get(student_id, 0.0)) > now_ts
            if not ai_plan and in_cooldown:
                ai_unavailable_reason = "AI temporary cooldown due to recent rate limiting."

            if not ai_plan and not in_cooldown:
                try:
                    ai_answer, _ = await chat_with_student_model(
                        question=ai_prompt,
                        current_user=current_user,
                        history=None,
                        # Use a non-RAG mode to avoid extra embedding/vector calls for this endpoint.
                        mode="academic_progress",
                    )
                    ai_plan = _extract_ai_drop_recommendation(ai_answer)
                    if not ai_plan:
                        ai_unavailable_reason = "AI returned an invalid or empty JSON recommendation."
                        _drop_ai_cooldown_until[student_id] = now_ts + _DROP_AI_COOLDOWN_SECONDS
                    else:
                        _cache_drop_ai_plan(cache_key=cache_key, now_ts=now_ts, plan=ai_plan)
                        _drop_ai_cooldown_until.pop(student_id, None)
                except MissingAIConfigError as exc:
                    ai_unavailable_reason = str(exc)
                    _drop_ai_cooldown_until[student_id] = now_ts + _DROP_AI_COOLDOWN_SECONDS
                except RateLimitedAIError as exc:
                    ai_unavailable_reason = str(exc)
                    _drop_ai_cooldown_until[student_id] = now_ts + _DROP_AI_COOLDOWN_SECONDS
                except ChatServiceError as exc:
                    ai_unavailable_reason = str(exc)
                    _drop_ai_cooldown_until[student_id] = now_ts + _DROP_AI_COOLDOWN_SECONDS
                except Exception as exc:
                    ai_unavailable_reason = f"Unexpected AI error: {str(exc)}"
                    _drop_ai_cooldown_until[student_id] = now_ts + _DROP_AI_COOLDOWN_SECONDS

    course_map = {c.code: c for c in current_courses}
    selected_items: List[DropRecommendationItem] = []

    elective_obj = ai_plan.get("elective") if isinstance(ai_plan, dict) else None
    if isinstance(elective_obj, dict):
        code = str(elective_obj.get("code") or "").strip()
        reason = str(elective_obj.get("reason") or "").strip()[:180]
        course = course_map.get(code)
        if course and reason and not _is_retake_course(course):
            selected_items.append(
                DropRecommendationItem(
                    code=course.code,
                    title=course.title,
                    type=course.tag,
                    credits=course.credits,
                    reason=reason,
                )
            )

    ai_others = ai_plan.get("others") if isinstance(ai_plan, dict) else []
    if isinstance(ai_others, list):
        for item in ai_others:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            reason = str(item.get("reason") or "").strip()[:180]
            course = course_map.get(code)
            if not course or not reason:
                continue
            if _is_retake_course(course):
                continue
            if any(existing.code == code for existing in selected_items):
                continue
            selected_items.append(
                DropRecommendationItem(
                    code=course.code,
                    title=course.title,
                    type=course.tag,
                    credits=course.credits,
                    reason=reason,
                )
            )

    if not selected_items:
        fallback_plan = _fallback_drop_plan(current_courses=current_courses, excess_credits=excess_credits)
        fallback_elective: Optional[DropRecommendationItem] = fallback_plan["elective"]
        fallback_others: List[DropRecommendationItem] = fallback_plan["others"]
        selected_items = ([fallback_elective] if fallback_elective else []) + fallback_others
        if ai_unavailable_reason:
            fallback_cache_plan: Dict[str, Any] = {
                "elective": fallback_elective.model_dump() if fallback_elective else None,
                "others": [item.model_dump() for item in fallback_others],
            }
            _cache_drop_ai_plan(cache_key=cache_key, now_ts=now_ts, plan=fallback_cache_plan)

    forced_elective_drops = max(0, len(elective_codes) - 1)
    current_selected_codes = {x.code for x in selected_items}
    if forced_elective_drops > 0:
        elective_candidates = [course_map[c] for c in elective_codes if c in course_map and not _is_retake_course(course_map[c])]
        keep_code = max(elective_candidates, key=lambda c: c.credits).code if elective_candidates else None
        must_drop_electives = [c for c in elective_candidates if c.code != keep_code]
        for c in must_drop_electives:
            if c.code in current_selected_codes:
                continue
            selected_items.append(
                DropRecommendationItem(
                    code=c.code,
                    title=c.title,
                    type=c.tag,
                    credits=c.credits,
                    reason="Only one elective should remain this semester.",
                )
            )
            current_selected_codes.add(c.code)

    dropped_credits = sum(x.credits for x in selected_items)
    remaining_needed = max(0.0, excess_credits - dropped_credits)
    if remaining_needed > 0:
        remaining_courses = [
            c for c in current_courses
            if c.code not in current_selected_codes and not _is_retake_course(c)
        ]
        remaining_courses.sort(key=lambda c: c.credits, reverse=True)
        for c in remaining_courses:
            selected_items.append(
                DropRecommendationItem(
                    code=c.code,
                    title=c.title,
                    type=c.tag,
                    credits=c.credits,
                    reason="Dropping this helps bring your credits under the limit.",
                )
            )
            current_selected_codes.add(c.code)
            remaining_needed = max(0.0, remaining_needed - c.credits)
            if remaining_needed <= 0:
                break

    final_elective = next((x for x in selected_items if _is_elective_course(course_map[x.code])), None)
    final_others = [x for x in selected_items if final_elective is None or x.code != final_elective.code]

    response_message = f"Recommended courses to drop to meet the {credit_limit:g}-credit limit."
    if ai_unavailable_reason:
        response_message = (
            f"Recommended courses to drop to meet the {credit_limit:g}-credit limit "
            "(fallback generated because AI is temporarily unavailable)."
        )

    return DropRecommendationResponse(
        exceeds_limit=True,
        message=response_message,
        credit_limit=credit_limit,
        current_total_credits=total_credits,
        credits_to_drop=excess_credits,
        elective=final_elective,
        others=final_others,
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

    effective_settings = await get_effective_enrollment_settings_for_user(current_user=current_user)
    enforce_enrollment_window_or_403(effective_settings)

    # Handle single string or list
    codes_to_enroll = []
    if isinstance(payload.selected_code, str):
        if "," in payload.selected_code:
            codes_to_enroll = [c.strip() for c in payload.selected_code.split(",")]
        else:
            codes_to_enroll = [payload.selected_code]
    elif isinstance(payload.selected_code, list):
        codes_to_enroll = payload.selected_code

    codes_to_enroll = [c for c in {str(code).strip() for code in codes_to_enroll} if c]
    successful_enrollments = 0

    active_enrollments = await Enrollment.find(
        Enrollment.student_id == student_id,
        Enrollment.semester_attend == str(current_semester),
        In(Enrollment.status, [EnrollmentStatus.ENROLLED, EnrollmentStatus.PENDING, EnrollmentStatus.WAITLISTED]),
    ).to_list()
    active_course_ids = {e.course_id for e in active_enrollments}

    active_courses = await Course.find(In(Course.course_code, list(active_course_ids))).to_list() if active_course_ids else []
    active_total_credits = float(sum(float(c.credits) for c in active_courses))

    candidate_courses: List[Course] = []
    for code in codes_to_enroll:
        if code in active_course_ids:
            continue
        course = await Course.find_one(Course.course_code == code)
        if course:
            candidate_courses.append(course)

    if effective_settings.max_courses is not None:
        projected_count = len(active_course_ids) + len(candidate_courses)
        if projected_count > int(effective_settings.max_courses):
            raise HTTPException(
                status_code=400,
                detail=f"Enrollment exceeds max_courses limit ({effective_settings.max_courses}).",
            )

    projected_total = active_total_credits + sum(float(c.credits) for c in candidate_courses)
    if projected_total > float(effective_settings.max_credits):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Enrollment exceeds max_credits limit ({effective_settings.max_credits:g}). "
                f"Projected total is {projected_total:g}."
            ),
        )

    passed_codes = await _get_passed_course_codes(current_user=current_user, student_id=student_id)
    for course in candidate_courses:
        missing_prereqs = [req for req in (course.prerequisites or []) if req not in passed_codes]
        if missing_prereqs:
            raise HTTPException(
                status_code=400,
                detail=f"Missing prerequisite(s) for {course.course_code}: {', '.join(missing_prereqs)}",
            )

    history = student_profile.get("academic_history", []) or current_user.get("academic_history", [])
    retake_codes = {str(h.get("course_code") or "").strip() for h in history if h.get("course_code")}

    for course in candidate_courses:
        new_enr = Enrollment(
            student_id=student_id,
            course_id=course.course_code,
            semester_attend=str(current_semester),
            status=EnrollmentStatus.PENDING,
            is_retake=course.course_code in retake_codes,
        )
        doc = new_enr.model_dump(by_alias=True, exclude_none=True)
        await Enrollment.get_motor_collection().insert_one(doc)
        successful_enrollments += 1

    final_total = projected_total
    remaining_limit = float(effective_settings.max_credits) - final_total

    return EnrollmentResponse(
        success=True,
        message="Enrollment request submitted successfully (Pending approval).",
        credit_usage={
            "total": final_total,
            "remaining_limit": remaining_limit,
            "max_credits": float(effective_settings.max_credits),
            "successful_enrollments": successful_enrollments,
        }
    )

