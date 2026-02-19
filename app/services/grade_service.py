from typing import List, Dict
from app.schemas.student import StudentResult, SemesterResult, AcademicSummary

GRADE_POINTS = {
    "A+": 4.0,
    "A": 4.0,
    "A-": 3.67,
    "B+": 3.33,
    "B": 3.0,
    "B-": 2.67,
    "C+": 2.33,
    "C": 2.0,
    "D": 1.0,
    "F": 0.0
}

def get_grade_point(grade: str) -> float:
    return GRADE_POINTS.get(grade, 0.0)

def calculate_course_points(grade: str, credits: float) -> float:
    points = get_grade_point(grade)
    return round(points * credits, 2)

def calculate_gpa(total_points: float, total_credits: float) -> float:
    if total_credits == 0:
        return 0.0
    return round(total_points / total_credits, 2)

def calculate_cgpa(cumulative_points: float, cumulative_credits: float) -> float:
    return calculate_gpa(cumulative_points, cumulative_credits)

def calculate_semester_gpa(results: List[StudentResult]) -> float:
    """Calculate GPA for a single semester."""
    total_points = sum(result.grade_points_earned or 0 for result in results)
    total_credits = sum(result.credit_unit or 0 for result in results)
    return calculate_gpa(total_points, total_credits)

def calculate_academic_summary(semesters: List[SemesterResult]) -> AcademicSummary:
    """Calculate overall academic summary including CGPA."""
    total_credits = sum(semester.total_credit_unit for semester in semesters)
    total_points = sum(semester.total_grade_points for semester in semesters)
    cgpa = calculate_cgpa(total_points, total_credits)
    
    return AcademicSummary(
        total_credits_earned=total_credits,
        total_grade_points=total_points,
        cgpa=cgpa,
        semesters=semesters
    )

def get_result_tag(grade: str) -> str:
    """Determine result tag based on grade."""
    if grade in ["A+", "A", "A-"]:
        return "Distinction"
    elif grade in ["B+", "B", "B-"]:
        return "Merit"
    elif grade in ["C+", "C"]:
        return "Passed"
    elif grade == "D":
        return "Pass"
    else:
        return "Failed"

def apply_retake_grade_logic(grade: str, status: str, is_retake: bool) -> str:
    """
    Apply retake grade logic: if is_retake=true and status changed to passed, set grade to static C (2.0 points).
    If still not passed, return original grade.
    """
    if is_retake and status in ["Passed", "Completed"]:
        return "C"  # Static C grade (2.0 points) for passed retakes
    return grade  # Return original grade if not retake or not passed
