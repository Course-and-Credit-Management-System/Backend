from typing import List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel

# Dashboard Summary
class Progress(BaseModel):
    completed_credits: float
    required_credits: float
    percentage: float

class DashboardSummary(BaseModel):
    gpa: float
    enrollment_status: str
    progress: Progress

# Activity
class ActivityItem(BaseModel):
    type: str
    title: str
    date: datetime
    priority: Optional[str] = None

# Degree Audit
class CreditProgress(BaseModel):
    earned: float
    required: float

class DegreeAudit(BaseModel):
    core_credits: CreditProgress
    elective_credits: CreditProgress
    major_specific: CreditProgress
    # Optional course-count progress bars: Core / Elective / Major / Overall
    # Each item: {"label": "...", "percentage": 0-100, "completed": int, "total": int}
    progress_bars: Optional[List[Dict]] = None

# Academic Status
class AcademicStatus(BaseModel):
    status: str
    tag: str
    standing_color: str
    updated_at: datetime

# Courses
class CourseSchedule(BaseModel):
    course_code: str
    title: str
    credits: float
    schedule: List[str]
    room: str

# Results
class StudentResult(BaseModel):
    course_code: str
    course_title: Optional[str] = None
    grade: str
    points: float
    status: str
    result_tag: Optional[str] = None
    review_status: str = "None"
    lecture_hours: Optional[int] = None
    tda_hours: Optional[int] = None
    credit_unit: Optional[int] = None
    grade_points_earned: Optional[float] = None

class SemesterResult(BaseModel):
    academic_year: str
    semester: str
    results: List[StudentResult]
    total_credit_unit: int
    total_grade_points: float
    gpa: float
    
class AcademicSummary(BaseModel):
    total_credits_earned: int
    total_grade_points: float
    cgpa: float
    semesters: List[SemesterResult]

class StudentProfile(BaseModel):
    name: str
    nrc: str
    sex: str
    dob: str # e.g. "October 22, 2004"
    
class CertificateData(BaseModel):
    student: StudentProfile
    period: str # e.g. "November 2023 - March 2024 (Semester III)"
    semester_result: SemesterResult
    
class CompleteAcademicRecord(BaseModel):
    student: StudentProfile
    academic_summary: AcademicSummary

# Review Request
class ReviewRequestCreate(BaseModel):
    reason: str
    evidence: Optional[str] = None

class GradeReview(BaseModel):
    request_id: str
    result_id: str
    course_code: str
    course_title: str
    current_grade: str
    requested_grade: Optional[str] = None
    reason: str
    evidence: Optional[str] = None
    status: str  # "Pending", "In Review", "Approved", "Rejected"
    submission_date: datetime
    admin_comment: Optional[str] = None
    resolved_date: Optional[datetime] = None

class ReviewRequestResponse(BaseModel):
    requestId: str
    status: str
    submissionDate: str
    adminComment: Optional[str] = None

class ReviewStatusResponse(BaseModel):
    request_id: str
    status: str
    review_details: Optional[GradeReview] = None

class ReviewListResponse(BaseModel):
    reviews: List[GradeReview]
    total: int

# Schedule Download
class ScheduleDownload(BaseModel):
    downloadToken: str
    fileName: str
    url: str

# Enrollment
class AvailableCourse(BaseModel):
    course_code: str
    title: str
    prerequisites_met: bool
    available_seats: int

class EnrollmentRequestPayload(BaseModel):
    student_id: str
    course_id: str

class EnrollmentRequestData(BaseModel):
    student_id: str
    course_id: str
    status: str
    submitted_at: datetime

class EnrollmentResponse(BaseModel):
    message: str
    request: EnrollmentRequestData

class EnrollmentAlerts(BaseModel):
    warnings: List[str]
    retakes: List[str]
