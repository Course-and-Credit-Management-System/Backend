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

router = APIRouter()

def _map_student_record(data: dict) -> schemas.CompleteAcademicRecord:
    profile = data.get("student_profile") or {}
    semesters_in = data.get("academic_history") or []
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
            # Use static credit unit of 3 for all courses
            credits = 3
            grade_val = r.get("grade") or ""
            gp = calculate_course_points(grade_val, 1) if grade_val else 0.0
            gpe = calculate_course_points(grade_val, credits) if grade_val else 0.0
            results_out.append(
                schemas.StudentResult(
                    course_code=r.get("course_code") or r.get("code") or "",
                    course_title=r.get("course_title") or r.get("title"),
                    grade=grade_val,
                    points=gp,
                    status=r.get("status") or "Completed",
                    result_tag=get_result_tag(r.get("grade") or ""),
                    review_status=r.get("review_status") or "None",
                    lecture_hours=2,
                    tda_hours=2,
                    credit_unit=credits,
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
    users = db["Users"]
    doc = None

    if user_id:
        doc = await users.find_one({"user_id": user_id})
        if not doc and ObjectId.is_valid(user_id):
            doc = await users.find_one({"_id": ObjectId(user_id)})

    if not doc:
        return get_mock_academic_record()
    
    # Ensure we pass a dict (Motor returns a dict)
    return _map_student_record(doc)

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

@router.get("/courses/current", response_model=List[schemas.CourseSchedule])
async def get_current_courses():
    """
    Returns the current semester's schedule and credits.
    """
    return [
        {
            "course_code": "CST-1010",
            "title": "Intro to Data Science",
            "credits": 3.0,
            "schedule": ["Mon 10:00-11:30", "Wed 10:00-11:30"],
            "room": "Bldg A, 302"
        },
        {
            "course_code": "CST-2020",
            "title": "Database Systems",
            "credits": 3.0,
            "schedule": ["Tue 13:00-14:30", "Thu 13:00-14:30"],
            "room": "Bldg B, 101"
        }
    ]

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
            period=f"{target_semester.academic_year} ({target_semester.semester})",
            semester_result=target_semester
        )
        pdf_buffer = generate_certificate_pdf(certificate_data)
        headers = {
            'Content-Disposition': f'attachment; filename="grading_certificate_{target_semester.academic_year}_{target_semester.semester}.pdf"'
        }
        return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)
    
    if (type or "").lower() == "year" and academic_year:
        year_semesters = [sem for sem in academic_record.academic_summary.semesters if sem.academic_year == academic_year]
        if not year_semesters:
            raise HTTPException(status_code=404, detail=f"No semesters found for academic year {academic_year}")
        summary = calculate_academic_summary(year_semesters)
        year_record = schemas.CompleteAcademicRecord(student=academic_record.student, academic_summary=summary)
        pdf_buffer = generate_complete_transcript_pdf(year_record)
        headers = {
            'Content-Disposition': f'attachment; filename="grading_certificate_{academic_year}.pdf"'
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
async def get_enrollment_alerts():
    """
    Returns warnings like 'Retake Subjects' or 'Credit Limit Exceeded'.
    """
    return {
        "warnings": ["Max credit limit reached (18/18)"],
        "retakes": ["CST-1005 (Failed last semester)"]
    }
