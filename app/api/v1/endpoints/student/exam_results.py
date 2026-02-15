from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.schemas.exam_result import ExamResultOut

router = APIRouter(prefix="/api/v1/student/exam-results", tags=["Student Exam Results"])

@router.get("", response_model=list[ExamResultOut])
async def my_exam_results(student_id: str, db=Depends(get_db)):
    results = await db["ExamResults"].find({"student_id": student_id}).to_list(500)
    for r in results:
        r.pop("_id", None)
    return results
