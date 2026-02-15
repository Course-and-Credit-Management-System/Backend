from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Depends
from fastapi.responses import StreamingResponse

from app.schemas import student as schemas
from app.core.database import get_db, get_database
from bson import ObjectId
from app.services.pdf_service import generate_certificate_pdf, generate_complete_transcript_pdf
from app.services.grade_service import (
    calculate_course_points, calculate_gpa, calculate_academic_summary, 
    get_result_tag
)
from app.api.v1.deps.auth import get_current_user
from app.services.enrollment_settings_service import get_effective_enrollment_settings_for_user

router = APIRouter()

def format_period_display(academic_year: str, semester: str) -> str:
    """Format period display name for PDF certificates"""
    # Convert "1st Year, First Sem(new)" to "First Year, First Semester"
    if "1st Year" in academic_year and "First Sem" in semester:
        return "First Year, First Semester"
    elif "1st Year" in academic_year and "Second Sem" in semester:
        return "First Year, Second Semester"
    elif "2nd Year" in academic_year and "First Sem" in semester:
        return "Second Year, First Semester"
    elif "2nd Year" in academic_year and "Second Sem" in semester:
        return "Second Year, Second Semester"
    elif "3rd Year" in academic_year and "First Sem" in semester:
        return "Third Year, First Semester"
    elif "3rd Year" in academic_year and "Second Sem" in semester:
        return "Third Year, Second Semester"
    elif "4th Year" in academic_year and "First Sem" in semester:
        return "Fourth Year, First Semester"
    elif "4th Year" in academic_year and "Second Sem" in semester:
        return "Fourth Year, Second Semester"
    # Fallback to original format if no pattern matches
    return f"{academic_year} ({semester})"

async def _get_col(db, names: list[str]):
    cols = await db.list_collection_names()
    for n in names:
        if n in cols:
            return db[n]
    return db[names[0]]

def _map_student_record(data: dict) -> schemas.CompleteAcademicRecord:
    profile = data.get("student_profile") or {}
    
    # Handle both processed data and raw academic_history
    semesters_in = data.get("academic_history") or []
    
    # If academic_history is empty but user has raw academic_history, use that
    if not semesters_in and "academic_history" in data:
        semesters_in = data["academic_history"]
    
    semesters_map = {}
    for entry in semesters_in:
        sem = entry.get("semester") or ""
        semesters_map.setdefault(sem, []).append(entry)
    semesters_out: List[schemas.SemesterResult] = []
    total_credits = 0
    total_points = 0.0
    for sem_name, entries in semesters_map.items():
        results_out: List[schemas.StudentResult] = []
        for r in entries:
            # Credits should only count for completed/passed courses
            status_val = (r.get("status") or "").strip()
            credits = r.get("credits", 3) or 3
            countable_statuses = {"Completed", "Passed"}
            grade_val = r.get("grade") or ""
            gp = calculate_course_points(grade_val, 1) if (grade_val and status_val in countable_statuses) else 0.0
            gpe = calculate_course_points(grade_val, credits) if (grade_val and status_val in countable_statuses) else 0.0
            results_out.append(
                schemas.StudentResult(
                    course_code=r.get("course_code") or r.get("code") or "",
                    course_title=r.get("course_title") or r.get("title"),
                    grade=grade_val,
                    points=gp,
                    status=status_val or "Unknown",
                    result_tag=get_result_tag(r.get("grade") or ""),
                    review_status=r.get("review_status") or "None",
                    lecture_hours=2,
                    tda_hours=2,
                    credit_unit=credits if status_val in countable_statuses else 0,
                    grade_points_earned=gpe,
                )
            )
        sem_credits = sum(res.credit_unit or 0 for res in results_out)
        sem_points = sum(res.grade_points_earned or 0 for res in results_out)
        sem_gpa = calculate_gpa(sem_points, sem_credits)
        academic_year = sem_name.split(" (")[0] if " (" in sem_name else sem_name
        semester_plain = sem_name.split(" (")[1].replace(")", "") if " (" in sem_name else sem_name
        semesters_out.append(
            schemas.SemesterResult(
                academic_year=academic_year,
                semester=semester_plain,
                results=results_out,
                total_credit_unit=sem_credits,
                total_grade_points=sem_points,
                gpa=sem_gpa,
            )
        )
        total_credits += sem_credits
        total_points += sem_points
    cgpa = calculate_gpa(total_points, total_credits)
    return schemas.CompleteAcademicRecord(
        student=schemas.StudentProfile(
            name=data.get("name") or data.get("full_name") or "",
            nrc=profile.get("nrc") or "",
            sex=profile.get("sex") or "",
            dob=profile.get("dob") or "",
        ),
        academic_summary=schemas.AcademicSummary(
            total_credits_earned=total_credits,
            total_grade_points=total_points,
            cgpa=cgpa,
            semesters=semesters_out,
        ),
    )

async def fetch_latest_academic_record(user_id: Optional[str] = None) -> schemas.CompleteAcademicRecord:
    db = await get_database()
    users = await _get_col(db, ["Users", "users"])
    enrollments = await _get_col(db, ["Enrollments", "enrollments"])
    courses = await _get_col(db, ["Courses", "courses"])
    
    # Get user info
    user_doc = None
    if user_id:
        user_doc = await users.find_one({"user_id": user_id})
        if not user_doc and ObjectId.is_valid(user_id):
            user_doc = await users.find_one({"_id": ObjectId(user_id)})

    if not user_doc:
        return get_mock_academic_record()
    
    # Get student's enrollments (support multiple possible field names)
    enroll_query = {
        "$or": [
            {"student_id": user_id},
            {"student_user_id": user_id},
            {"user_id": user_id},
        ]
    }
    enrollment_records = await enrollments.find(enroll_query).to_list(None)
    
    if not enrollment_records:
        return get_mock_academic_record()
    
    # Build academic history from enrollments
    academic_history = []
    for enrollment in enrollment_records:
        # Resolve course doc robustly by _id or course_code
        course_id_or_code = enrollment.get("course_id", "") or enrollment.get("course_code", "")
        course = None
        if course_id_or_code:
            course = await courses.find_one({"_id": course_id_or_code})
            if not course:
                course = await courses.find_one({"course_code": course_id_or_code})
        
        academic_history.append({
            "course_code": (course or {}).get("course_code", course_id_or_code),
            "course_title": (course or {}).get("title", course_id_or_code),
            "grade": enrollment.get("grade", ""),
            "status": enrollment.get("status", "Unknown"),
            "semester": enrollment.get("semesterAttend", ""),
            "credits": (course or {}).get("credits", enrollment.get("credits", 3)),
            "points": enrollment.get("points", 0),
            "is_retake": enrollment.get("is_retake", False)
        })
    
    # Create a combined document for mapping
    combined_doc = dict(user_doc)
    combined_doc["academic_history"] = academic_history
    
    # Ensure we pass a dict (Motor returns a dict)
    return _map_student_record(combined_doc)

# Mock Data for Multiple Semesters
def get_mock_academic_record():
    """Minimal mock academic data for fallback."""
    semester_results = [
        schemas.StudentResult(
            course_code="CST-1001",
            course_title="Intro to Programming",
            grade="A",
            points=4.00,
            status="Passed",
            result_tag=get_result_tag("A"),
            lecture_hours=2,
            tda_hours=2,
            credit_unit=3,
            grade_points_earned=12.00
        ),
        schemas.StudentResult(
            course_code="MTH-1001",
            course_title="Calculus I",
            grade="A-",
            points=3.67,
            status="Passed",
            result_tag=get_result_tag("A-"),
            lecture_hours=2,
            tda_hours=2,
            credit_unit=3,
            grade_points_earned=11.01
        ),
    ]
    sem_credits = sum(r.credit_unit or 0 for r in semester_results)
    sem_points = sum(r.grade_points_earned or 0 for r in semester_results)
    sem_gpa = calculate_gpa(sem_points, sem_credits)
    semesters = [
        schemas.SemesterResult(
            academic_year="First Year (2024 - 2025)",
            semester="Semester I",
            results=semester_results,
            total_credit_unit=sem_credits,
            total_grade_points=sem_points,
            gpa=sem_gpa
        )
    ]
    academic_summary = calculate_academic_summary(semesters)
    return schemas.CompleteAcademicRecord(
        student=schemas.StudentProfile(
            name="Sample Student",
            nrc="XX/XXXXXX",
            sex="Male",
            dob="January 1, 2004"
        ),
        academic_summary=academic_summary
    )

# Mock Grade Review Data
mock_reviews = [
    schemas.GradeReview(
        request_id="REV-001",
        result_id="CST-1003",
        course_code="CST-1003",
        course_title="Fundamentals of Programming II",
        current_grade="B+",
        reason="Believe there was an error in the final exam grading.",
        evidence="Attached exam paper and expected solution.",
        status="In Review",
        submission_date=datetime(2024, 1, 28, 10, 0, 0),
        admin_comment="Under review by instructor.",
        resolved_date=None
    ),
    schemas.GradeReview(
        request_id="REV-002",
        result_id="MTH-1002",
        course_code="MTH-1002",
        course_title="Mathematics II",
        current_grade="B-",
        reason="Requesting re-evaluation of midterm exam.",
        evidence="Provided additional work samples.",
        status="Approved",
        submission_date=datetime(2024, 1, 15, 14, 30, 0),
        admin_comment="Grade updated to B after review.",
        resolved_date=datetime(2024, 1, 20, 16, 0, 0)
    )
]

# 6. Student - Academic Overview

@router.get("/dashboard-summary", response_model=schemas.DashboardSummary)
async def get_dashboard_summary(current_user=Depends(get_current_user)):
    """
    Returns GPA, current enrollment status, and degree progress percentages.
    """
    academic_record = await fetch_latest_academic_record(current_user.get("user_id"))
    return {
        "gpa": academic_record.academic_summary.cgpa,
        "enrollment_status": "Enrolled",
        "progress": {
            "completed_credits": academic_record.academic_summary.total_credits_earned,
            "required_credits": 132,  # From real data
            "percentage": round((academic_record.academic_summary.total_credits_earned / 132) * 100, 1)
        }
    }

@router.get("/activity", response_model=List[schemas.ActivityItem])
async def get_recent_activity():
    """
    Returns 'Recent Activity' list (grades posted, announcements).
    """
    return [
        {
            "type": "Announcement",
            "title": "Final Exam Schedule Posted",
            "date": datetime(2024, 1, 25, 9, 0, 0),
            "priority": "High"
        },
        {
            "type": "Grade",
            "title": "Grade posted for CST-1010",
            "date": datetime(2024, 1, 20, 15, 0, 0)
        }
    ]

@router.get("/degree-audit", response_model=schemas.DegreeAudit)
async def get_degree_audit():
    """
    Returns breakdown of Core vs Elective credits.
    """
    return {
        "core_credits": { "earned": 45, "required": 60 },
        "elective_credits": { "earned": 12, "required": 15 },
        "major_specific": { "earned": 7, "required": 10 }
    }

@router.get("/status", response_model=schemas.AcademicStatus)
async def get_academic_status():
    """
    Returns the current academic standing for the 'Academic Status Tag'.
    """
    return {
        "status": "Active",
        "tag": "Good Standing",
        "standing_color": "green",
        "updated_at": datetime(2024, 2, 1, 10, 0, 0)
    }

# 7. Student - Courses & Results

@router.get("/courses/current", response_model=schemas.CourseSchedule)
async def get_current_courses(current_user=Depends(get_current_user)):
    """
    Returns the current semester's schedule and credits.
    """
    db = await get_database()
    enrollments = await _get_col(db, ["Enrollments", "enrollments"])
    courses = await _get_col(db, ["Courses", "courses"])
    
    user_id = current_user.get("user_id")
    effective_settings = await get_effective_enrollment_settings_for_user(current_user=current_user)
    
    # Get current enrollments for the student (support multiple possible field names)
    enroll_query = {
        "$or": [
            {"student_id": user_id},
            {"student_user_id": user_id},
            {"user_id": user_id},
        ]
    }
    enrollment_records = await enrollments.find(enroll_query).to_list(None)
    
    current_courses = []
    total_credits = 0
    
    for enrollment in enrollment_records:
        # Get course details
        course_id_or_code = enrollment.get("course_id", "") or enrollment.get("course_code", "")
        course = None
        if course_id_or_code:
            # Try by _id first (many datasets store string IDs like "c_004")
            course = await courses.find_one({"_id": course_id_or_code})
            # Fallback: some datasets store course_id as course_code (e.g., "CS-101")
            if not course:
                course = await courses.find_one({"course_code": course_id_or_code})
        
        course_data = {
            "code": (course or {}).get("course_code", course_id_or_code),
            "title": (course or {}).get("title", course_id_or_code),
            "credits": (course or {}).get("credits", enrollment.get("credits", 3)),
            "instructor": (course or {}).get("instructor", "TBA"),
            "location": (course or {}).get("room", "TBA"),
            "is_retake": enrollment.get("is_retake", False),
            "tag": "Core",
        }
        current_courses.append(course_data)
        total_credits += course_data["credits"]
    
    # Return the structure expected by frontend
    return {
        "semester_name": "Current Semester",
        "total_credits": total_credits,
        "max_credits": float(effective_settings.max_credits),
        "courses_count": len(current_courses),
        "courses": current_courses
    }

@router.get("/results", response_model=schemas.CompleteAcademicRecord)
async def get_student_results(user_id: Optional[str] = None, current_user=Depends(get_current_user)):
    uid = user_id or current_user.get("user_id")
    return await fetch_latest_academic_record(uid)

@router.get("/results/summary", response_model=schemas.AcademicSummary)
async def get_academic_summary(user_id: Optional[str] = None, current_user=Depends(get_current_user)):
    uid = user_id or current_user.get("user_id")
    record = await fetch_latest_academic_record(uid)
    return record.academic_summary

@router.get("/results/pdf")
async def download_results_pdf(current_user=Depends(get_current_user)):
    """
    Generates and downloads of complete grading transcript PDF.
    """
    academic_record = await fetch_latest_academic_record(current_user.get("user_id"))
    pdf_buffer = generate_complete_transcript_pdf(academic_record)
    
    headers = {
        'Content-Disposition': 'attachment; filename="complete_academic_transcript.pdf"'
    }
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)

@router.get("/results/certificate/pdf")
async def download_certificate_pdf(
    type: Optional[str] = "semester",
    academic_year: Optional[str] = None,
    semester: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """
    Generates and downloads of single semester certificate PDF (latest semester).
    """
    academic_record = await fetch_latest_academic_record(current_user.get("user_id"))
    
    if (type or "").lower() == "semester":
        target_semester = None
        if academic_year and semester:
            for sem in academic_record.academic_summary.semesters:
                if sem.academic_year == academic_year and sem.semester == semester:
                    target_semester = sem
                    break
        if not target_semester:
            if academic_record.academic_summary.semesters:
                target_semester = academic_record.academic_summary.semesters[-1]
            else:
                raise HTTPException(status_code=404, detail="No semester data found")
        
        certificate_data = schemas.CertificateData(
            student=academic_record.student,
            period=format_period_display(target_semester.academic_year, target_semester.semester),
            semester_result=target_semester
        )
        pdf_buffer = generate_certificate_pdf(certificate_data)
        headers = {
            'Content-Disposition': f'attachment; filename="grading_certificate_{target_semester.academic_year}_{target_semester.semester}.pdf"'
        }
        return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)
    
    if (type or "").lower() == "year" and academic_year:
        # Handle year-level matching (e.g., "Second Year" should match "2nd Year, First Sem" and "2nd Year, Second Sem")
        year_semesters = []
        for sem in academic_record.academic_summary.semesters:
            sem_academic_year = sem.academic_year
            if (academic_year == "First Year" and ("1st Year" in sem_academic_year or "First Year" in sem_academic_year)) or \
               (academic_year == "Second Year" and ("2nd Year" in sem_academic_year or "Second Year" in sem_academic_year)) or \
               (academic_year == "Third Year" and ("3rd Year" in sem_academic_year or "Third Year" in sem_academic_year)) or \
               (academic_year == "Fourth Year" and ("4th Year" in sem_academic_year or "Fourth Year" in sem_academic_year)):
                year_semesters.append(sem)
        
        # Fallback to exact match if no year-level matches found
        if not year_semesters:
            year_semesters = [sem for sem in academic_record.academic_summary.semesters if sem.academic_year == academic_year]
        
        if not year_semesters:
            raise HTTPException(status_code=404, detail=f"No semesters found for academic year {academic_year}")
        
        summary = calculate_academic_summary(year_semesters)
        year_record = schemas.CompleteAcademicRecord(student=academic_record.student, academic_summary=summary)
        pdf_buffer = generate_complete_transcript_pdf(year_record)
        headers = {
            'Content-Disposition': f'attachment; filename="grading_certificate_{academic_year.replace(" ", "_")}.pdf"'
        }
        return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)
    
    # default/all: full transcript
    pdf_buffer = generate_complete_transcript_pdf(academic_record)
    headers = {
        'Content-Disposition': 'attachment; filename="complete_grading_certificate.pdf"'
    }
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)

@router.get("/schedule/download", response_model=schemas.ScheduleDownload)
async def download_schedule():
    """
    Triggers PDF generation for 'Download Schedule'.
    """
    return {
        "downloadToken": "pdf_778899_auth",
        "fileName": "Semester_Schedule_Spring_2024.pdf",
        "url": "https://uniportal.edu/api/files/download/schedule_8801.pdf"
    }

@router.get("/reviews", response_model=schemas.ReviewListResponse)
async def get_grade_reviews():
    """
    Returns all grade review requests for the student.
    """
    return {
        "reviews": mock_reviews,
        "total": len(mock_reviews)
    }

@router.post("/results/{resultId}/review-request", response_model=schemas.ReviewRequestResponse)
async def request_grade_review(
    resultId: str = Path(..., title="The ID of the result to review"),
    payload: schemas.ReviewRequestCreate = None
):
    """
    Submits a formal request for a grade review.
    """
    # Find the course from academic record
    academic_record = get_mock_academic_record()
    course_info = None
    
    for semester in academic_record.academic_summary.semesters:
        for result in semester.results:
            if result.course_code == resultId:
                course_info = result
                break
        if course_info:
            break
    
    if not course_info:
        raise HTTPException(status_code=404, detail=f"Course {resultId} not found")
    
    # Create new review request
    new_review = schemas.GradeReview(
        request_id=f"REV-{len(mock_reviews) + 1:03d}",
        result_id=resultId,
        course_code=course_info.course_code,
        course_title=course_info.course_title or course_info.course_code,
        current_grade=course_info.grade,
        reason=payload.reason if payload else "Grade review requested",
        evidence=payload.evidence if payload else None,
        status="Pending",
        submission_date=datetime.now(),
        admin_comment=None,
        resolved_date=None
    )
    
    mock_reviews.append(new_review)
    
    return {
        "requestId": new_review.request_id,
        "status": new_review.status,
        "submissionDate": new_review.submission_date.strftime("%Y-%m-%d"),
        "adminComment": new_review.admin_comment
    }

@router.get("/results/{resultId}/review-status", response_model=schemas.ReviewStatusResponse)
async def get_review_status(resultId: str):
    """
    Tracks the progress of a requested review.
    """
    # Find review for this result
    review = next((r for r in mock_reviews if r.result_id == resultId), None)
    
    if not review:
        raise HTTPException(status_code=404, detail=f"Review for {resultId} not found")
    
    return {
        "request_id": review.request_id,
        "status": review.status,
        "review_details": review
    }

# 8. Student - Enrollment Process

@router.get("/enrollment/available", response_model=List[schemas.AvailableCourse])
async def get_available_courses():
    """
    Returns courses available for registration based on prerequisites.
    """
    return [
        {
            "course_code": "CST-2020",
            "title": "Database Systems",
            "prerequisites_met": True,
            "available_seats": 15
        },
        {
            "course_code": "CST-2030",
            "title": "Web Development II",
            "prerequisites_met": True,
            "available_seats": 8
        }
    ]

@router.post("/enrollment/request", response_model=schemas.EnrollmentResponse)
async def request_enrollment(payload: schemas.EnrollmentRequestPayload = None):
    """
    Submits a request to enroll in a specific course.
    """
    # Use mock data if payload is missing or just return static response as requested
    student_id = payload.student_id if payload else "TNT-8801"
    course_id = payload.course_id if payload else "65b9f789eabc"
    
    return {
        "message": "Enrollment request submitted",
        "request": {
            "student_id": student_id,
            "course_id": course_id,
            "status": "Pending",
            "submitted_at": datetime(2024, 2, 1, 10, 0, 0)
        }
    }

@router.get("/enrollment/alerts", response_model=schemas.EnrollmentAlerts)
async def get_enrollment_alerts(current_user=Depends(get_current_user)):
    """
    Returns warnings like 'Retake Subjects' or 'Credit Limit Exceeded'.
    """
    effective_settings = await get_effective_enrollment_settings_for_user(current_user=current_user)
    limit = float(effective_settings.max_credits)
    return {
        "warnings": [f"Max credit limit reached ({limit:g}/{limit:g})"],
        "retakes": ["CST-1005 (Failed last semester)"]
    }

@router.get("/progress")
async def get_degree_progress(current_user=Depends(get_current_user)):
    """
    Calculate student's degree progress percentage.
    
    Returns:
    - Total courses (Core + Elective) from Courses collection
    - Completed courses (from Enrollment with status="Passed" or user's academic_history)
    - Progress percentage for each category
    - Overall progress
    """
    print("PROGRESS DEBUG: Endpoint called!")
    
    if current_user.get("role") != "student":
        raise HTTPException(status_code=403, detail="Student access required")
    
    student_id = current_user.get("user_id")
    print(f"PROGRESS DEBUG: Student ID: {student_id}")
    print(f"PROGRESS DEBUG: User has academic_history: {bool(current_user.get('academic_history'))}")
    if current_user.get('academic_history'):
        print(f"PROGRESS DEBUG: Academic history length: {len(current_user.get('academic_history', []))}")
    
    db = await get_database()
    
    # Get collections
    courses_col = await _get_col(db, ["Courses", "courses"])
    enrollment_col = await _get_col(db, ["Enrollment", "enrollment"])
    
    # Get all courses and categorize them
    all_courses = []
    async for course in courses_col.find({}):
        all_courses.append(course)
    
    # Separate core and elective courses
    core_courses = [c for c in all_courses if c.get("type", "").lower() == "core"]
    elective_courses = [c for c in all_courses if c.get("type", "").lower() == "elective"]
    
    # Get student's passed courses from enrollment
    passed_enrollments = []
    async for enrollment in enrollment_col.find({
        "student_id": student_id,
        "status": "Passed"
    }):
        passed_enrollments.append(enrollment)
    
    # If no enrollments found, use academic_history from user data
    if not passed_enrollments and current_user.get("academic_history"):
        academic_history = current_user.get("academic_history", [])
        # Convert academic_history entries to enrollment-like format
        for course_entry in academic_history:
            if course_entry.get("status") in ["Completed", "Passed"]:
                passed_enrollments.append({
                    "course_id": course_entry.get("course_id"),
                    "course_code": course_entry.get("course_code"),
                    "status": course_entry.get("status"),
                    "grade": course_entry.get("grade"),
                    "credits": course_entry.get("credits")
                })
    
    # Get passed course IDs (try both course_id and course_code)
    passed_course_ids = []
    for enrollment in passed_enrollments:
        course_id = enrollment.get("course_id") or enrollment.get("course_code")
        if course_id:
            passed_course_ids.append(course_id)
    
    # Count completed courses by type
    completed_core = 0
    completed_elective = 0
    
    for course_id in passed_course_ids:
        # Find the course to determine its type
        # Try multiple matching strategies
        course = None
        for c in all_courses:
            if (c.get("course_code") == course_id or 
                c.get("_id") == course_id or
                c.get("course_code") == course_id):
                course = c
                break
        
        if course:
            if course.get("type", "").lower() == "core":
                completed_core += 1
            elif course.get("type", "").lower() == "elective":
                completed_elective += 1
    
    # Calculate percentages
    total_core = len(core_courses)
    total_elective = len(elective_courses)
    total_courses = total_core + total_elective
    
    core_percentage = (completed_core / total_core * 100) if total_core > 0 else 0
    elective_percentage = (completed_elective / total_elective * 100) if total_elective > 0 else 0
    overall_percentage = ((completed_core + completed_elective) / total_courses * 100) if total_courses > 0 else 0
    
    return {
        "student_id": student_id,
        "total_courses": {
            "core": total_core,
            "elective": total_elective,
            "overall": total_courses
        },
        "completed_courses": {
            "core": completed_core,
            "elective": completed_elective,
            "overall": completed_core + completed_elective
        },
        "progress_percentage": {
            "core": round(core_percentage, 2),
            "elective": round(elective_percentage, 2),
            "overall": round(overall_percentage, 2)
        },
        "passed_course_details": passed_enrollments
    }
