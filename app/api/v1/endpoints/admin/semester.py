from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pymongo import UpdateOne

from app.api.v1.deps.auth import require_admin
from app.core.database import get_database

router = APIRouter(prefix="/admin/semester", tags=["admin-semester"])


def _parse_current_year(value: Any) -> Tuple[int, int, str]:
    raw = str(value or "").strip()
    normalized = raw.lower()

    year = 1
    semester = 1
    version = "new"

    if "5th" in normalized:
        year = 5
    elif "4th" in normalized:
        year = 4
    elif "3rd" in normalized:
        year = 3
    elif "2nd" in normalized:
        year = 2

    if "second sem" in normalized or "2nd sem" in normalized:
        semester = 2

    if "(old)" in normalized or "old ." in normalized:
        version = "old"
    elif "(new)" in normalized or "new ." in normalized:
        version = "new"

    return year, semester, version


def _to_current_year_string(year: int, semester: int, version: str) -> str:
    prefix = "Old" if version == "old" else "New"
    ordinals = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
    year_label = ordinals.get(year, f"{year}th")
    sem_label = "First" if semester == 1 else "Second"
    return f"{prefix} . {year_label} Year . {sem_label} Sem"


@router.post("/advance")
async def advance_semester(
    current_user: Dict[str, Any] = Depends(require_admin),
):
    db = await get_database()

    enrollments_col = db["Enrollments"]
    exam_results_col = db["ExamResults"]
    users_col = db["Users"]

    enrolled_count = await enrollments_col.count_documents({"status": "Enrolled"})
    exam_results_count = await exam_results_col.count_documents({})

    if enrolled_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No enrolled records found in Enrollments. Semester cannot be advanced.",
        )

    if enrolled_count != exam_results_count:
        raise HTTPException(
            status_code=409,
            detail=(
                "Semester advance blocked: Enrollments(status='Enrolled') count "
                f"({enrolled_count}) must equal ExamResults count ({exam_results_count})."
            ),
        )

    students = await users_col.find(
        {"role": {"$in": ["student", "Student"]}},
        {"_id": 1, "student_profile.current_year": 1},
    ).to_list(length=None)

    if not students:
        raise HTTPException(status_code=404, detail="No student records found.")

    bulk_ops = []
    skipped_max_year = 0
    advanced_students = 0

    for student in students:
        student_profile = student.get("student_profile") or {}
        current_year_value = student_profile.get("current_year")
        year, semester, version = _parse_current_year(current_year_value)

        if semester == 1:
            next_year, next_semester = year, 2
        else:
            if year >= 5:
                skipped_max_year += 1
                continue
            next_year, next_semester = year + 1, 1

        next_current_year = _to_current_year_string(next_year, next_semester, version)

        bulk_ops.append(
            UpdateOne(
                {"_id": student["_id"]},
                {"$set": {"student_profile.current_year": next_current_year}},
            )
        )
        advanced_students += 1

    if not bulk_ops:
        raise HTTPException(
            status_code=400,
            detail="No eligible students to advance. All matching students are already at final term.",
        )

    bulk_result = await users_col.bulk_write(bulk_ops, ordered=False)

    return {
        "success": True,
        "message": "Semester advanced successfully.",
        "triggered_by": str(current_user.get("user_id") or ""),
        "counts": {
            "enrollments_enrolled": enrolled_count,
            "exam_results_total": exam_results_count,
            "students_advanced": advanced_students,
            "students_skipped_final_term": skipped_max_year,
            "db_modified": bulk_result.modified_count,
        },
    }
