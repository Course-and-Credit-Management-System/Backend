from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.schemas.exam_result import ExamResultOut

router = APIRouter(prefix="/api/v1/student/exam-results", tags=["Student Exam Results"])

@router.get("", response_model=list[ExamResultOut])
async def my_exam_results(student_id: str, db=Depends(get_db)):
    results = await db["Enrollments"].find({"student_id": student_id}).to_list(500)
    
    out = []
    for r in results:
        r.pop("_id", None)
        uid = r.get("student_id")
        
        sa = str(r.get("semesterAttend") or "").lower()
        yr_val = 1
        sem_val = 1
        if "2nd" in sa or "second year" in sa: yr_val = 2
        elif "3rd" in sa or "third year" in sa: yr_val = 3
        elif "4th" in sa or "fourth year" in sa: yr_val = 4
        elif "5th" in sa or "fifth year" in sa: yr_val = 5
        if "second sem" in sa or "sem 2" in sa: sem_val = 2
        
        # Mapped to match ExamResultOut and Admin response formats
        # We need to make sure we parse scores properly for float representation
        exam_score = r.get("scores", 0)
        try:
            exam_score = float(exam_score) if exam_score is not None else 0.0
        except (ValueError, TypeError):
            exam_score = 0.0

        mapped_result = {
            "student_id": uid,
            "course_code": r.get("course_id", ""),
            "year": yr_val,
            "semester": sem_val,
            "exam_score": exam_score,
            "grade": r.get("grade", "F"),
            "grade_point": r.get("points", 0),
            "status": r.get("status", "Failed"),
            "is_retake": r.get("is_retake", False),
            "semesterAttend": r.get("semesterAttend")
        }
        out.append(mapped_result)
        
    return out
