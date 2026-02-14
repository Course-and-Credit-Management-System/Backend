from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.core.database import get_db
from app.schemas.exam_result import ExamResultUpsertIn, ExamResultOut
from app.services.grading_service import score_to_grade
from io import BytesIO
import openpyxl


router = APIRouter(prefix="/exam-results", tags=["Admin Exam Results"])


def validate_year_section_major(year: int, section: str | None, major: str | None) -> tuple[str | None, str | None]:
    """
    Validate and return (section, major) based on year rules:
    - Year 1-2: section required (A/B/C), no major
    - Year 3: section required (A/B/C), major required (CS/CT)
    - Year 4-5: major required, no section
    """
    if year in [1, 2]:
        if not section or section not in ["A", "B", "C"]:
            raise ValueError(f"Section (A/B/C) is required for year {year}")
        return section, None
    elif year == 3:
        if not section or section not in ["A", "B", "C"]:
            raise ValueError("Section (A/B/C) is required for year 3")
        if not major or major not in ["CS", "CT"]:
            raise ValueError("Major (CS/CT) is required for year 3")
        return section, major
    elif year in [4, 5]:
        if not major:
            raise ValueError(f"Major is required for year {year}")
        return None, major
    else:
        raise ValueError(f"Invalid year: {year}. Must be 1-5.")


@router.post("/import-excel")
async def import_exam_results_excel(
    file: UploadFile = File(...),
    db=Depends(get_db),
):
    if not file.filename.endswith(".xlsx"):
        return {"success": False, "message": "Only .xlsx files are supported"}

    content = await file.read()
    wb = openpyxl.load_workbook(BytesIO(content))
    ws = wb.active  # first sheet

    # Read header row
    headers = []
    for cell in ws[1]:
        headers.append(str(cell.value).strip().lower() if cell.value else "")

    # Required columns: student_id, course_code, year, semester, exam_score
    # Optional columns: section (for years 1-3), major (for years 3-5)
    required = {"student_id", "course_code", "year", "semester", "exam_score"}
    if not required.issubset(set(headers)):
        return {
            "success": False,
            "message": f"Excel must include columns: {sorted(list(required))}. Optional: section, major"
        }

    header_index = {h: i for i, h in enumerate(headers)}

    inserted = 0
    updated = 0
    errors = []

    for row_num in range(2, ws.max_row + 1):
        row = [ws.cell(row=row_num, column=c).value for c in range(1, ws.max_column + 1)]

        # Skip empty rows
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        try:
            student_id = str(row[header_index["student_id"]]).strip()
            course_code = str(row[header_index["course_code"]]).strip()
            year = int(row[header_index["year"]])
            semester = int(row[header_index["semester"]])
            exam_score = float(row[header_index["exam_score"]])

            # Get optional section and major
            section = None
            major = None
            if "section" in header_index and row[header_index["section"]]:
                section = str(row[header_index["section"]]).strip().upper()
            if "major" in header_index and row[header_index["major"]]:
                major = str(row[header_index["major"]]).strip().upper()

            # Validate year, section, major combination
            section, major = validate_year_section_major(year, section, major)

            # Validate semester
            if semester not in [1, 2]:
                raise ValueError(f"Semester must be 1 or 2, got {semester}")

            grade, grade_point, status = score_to_grade(exam_score)

            doc = {
                "student_id": student_id,
                "course_code": course_code,
                "year": year,
                "semester": semester,
                "section": section,
                "major": major,
                "exam_score": exam_score,
                "grade": grade,
                "grade_point": grade_point,
                "status": status,
            }

            # Filter for upsert - unique by student, course, year, semester
            filt = {
                "student_id": student_id,
                "course_code": course_code,
                "year": year,
                "semester": semester,
            }

            res = await db["ExamResults"].update_one(filt, {"$set": doc}, upsert=True)
            if res.matched_count == 0:
                inserted += 1
            else:
                updated += 1

        except Exception as e:
            errors.append({"row": row_num, "error": str(e)})

    return {
        "success": True,
        "inserted": inserted,
        "updated": updated,
        "errors": errors,
    }


@router.get("")
async def list_exam_results(
    course_code: str | None = None,
    year: int | None = None,
    semester: int | None = None,
    major: str | None = None,
    section: str | None = None,
    db=Depends(get_db),
):
    """List exam results. Returns all matching records (no limit)."""
    query = {}
    if course_code: query["course_code"] = course_code
    if year is not None and year != 0: query["year"] = year
    if semester is not None and semester != 0: query["semester"] = semester
    if major: query["major"] = major
    if section: query["section"] = section

    results = await db["ExamResults"].find(query).to_list(2000)

    out = []
    for r in results:
        r.pop("_id", None)
        user = await db["Users"].find_one(
            {"user_id": r["student_id"]},
            {"_id": 0, "name": 1}
        )
        r["student_name"] = user["name"] if user else None
        # Ensure section/major are JSON-serializable (handle None, empty string)
        if r.get("section") == "" or r.get("section") is None:
            r["section"] = None
        if r.get("major") == "" or r.get("major") is None:
            r["major"] = None
        out.append(r)

    return out

@router.delete("")
async def delete_exam_result(
    student_id: str,
    course_code: str,
    year: int,
    semester: int,
    db=Depends(get_db),
):
    filt = {
        "student_id": student_id,
        "course_code": course_code,
        "year": year,
        "semester": semester,
    }

    res = await db["ExamResults"].delete_one(filt)
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Exam result not found")

    return {"success": True}


@router.post("", response_model=ExamResultOut)
async def upsert_exam_result(payload: ExamResultUpsertIn, db=Depends(get_db)):
    grade, grade_point, status = score_to_grade(payload.exam_score)

    # ---- find student name ----
    user_doc = await db["Users"].find_one({"user_id": payload.student_id})
    student_name = user_doc.get("name") if user_doc else None

    doc = {
        **payload.model_dump(),
        "student_name": student_name,
        "grade": grade,
        "grade_point": grade_point,
        "status": status,
    }

    # Filter for upsert - unique by student, course, year, semester
    filt = {
        "student_id": payload.student_id,
        "course_code": payload.course_code,
        "year": payload.year,
        "semester": payload.semester,
    }

    await db["ExamResults"].update_one(filt, {"$set": doc}, upsert=True)

    return doc
