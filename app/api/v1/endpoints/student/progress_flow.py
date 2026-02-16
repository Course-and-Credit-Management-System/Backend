from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_database
from app.api.v1.deps.auth import get_current_user
import re
from app.api.v1.endpoints.student.academic import fetch_latest_academic_record

router = APIRouter()

async def _get_col(db, names: list[str]):
    cols = await db.list_collection_names()
    for n in names:
        if n in cols:
            return db[n]
    return db[names[0]]

def _parse_program_type(academic_year: str) -> str:
    s = str(academic_year or "")
    s = s.replace("–", "-").replace("—", "-").replace("/", "-").replace("to", "-").strip()
    m = re.search(r"(\d{4})", s)
    if not m:
        return "4-year"
    try:
        start = int(m.group(1))
    except Exception:
        return "4-year"
    return "5-year" if start < 2024 else "4-year"

def _program_rule_note(program_type: str) -> str:
    return "4-year program (2024-2025 and later)" if program_type == "4-year" else "5-year program (before 2024-2025)"

def _valid_options(program_type: str):
    years = ["First Year", "Second Year", "Third Year", "Fourth Year"]
    if program_type == "5-year":
        years.append("Fifth Year")
    semesters = ["First Semester", "Second Semester"]
    return years, semesters
 
def _normalize_ay(s: str) -> str:
    s = str(s or "").strip()
    return s.replace("–", "-").replace("—", "-").replace("/", "-").replace("to", "-")
 
def _extract_year_pair(s: str) -> tuple[int | None, int | None]:
    m = re.search(r"(\d{4})\s*[-–—]\s*(\d{4})", s or "")
    if not m:
        return None, None
    try:
        a = int(m.group(1))
        b = int(m.group(2))
        return a, b
    except Exception:
        return None, None
 
def _derive_enrollment_year(record) -> str | None:
    pairs = []
    for sem in getattr(record.academic_summary, "semesters", []) or []:
        ay = getattr(sem, "academic_year", "") or ""
        se = getattr(sem, "semester", "") or ""
        a1, b1 = _extract_year_pair(ay)
        a2, b2 = _extract_year_pair(se)
        if a1 and b1:
            pairs.append((a1, b1, ay.lower()))
        if a2 and b2:
            pairs.append((a2, b2, se.lower()))
    if not pairs:
        return None
    pairs.sort(key=lambda x: x[0])
    y = pairs[0]
    return f"{y[0]}-{y[1]}"
 
def _parse_profile_current(raw: str | None) -> tuple[str | None, str | None, str | None]:
    s = (raw or "").strip().lower()
    if not s:
        return None, None, None
    yr = None
    sm = None
    if "1st" in s or "first year" in s or "year 1" in s or "1st year" in s:
        yr = "First Year"
    elif "2nd" in s or "second year" in s or "year 2" in s or "2nd year" in s:
        yr = "Second Year"
    elif "3rd" in s or "third year" in s or "year 3" in s or "3rd year" in s:
        yr = "Third Year"
    elif "4th" in s or "fourth year" in s or "year 4" in s or "4th year" in s:
        yr = "Fourth Year"
    elif "5th" in s or "fifth year" in s or "year 5" in s or "5th year" in s:
        yr = "Fifth Year"
    if "first sem" in s or "semester i" in s or "first semester" in s or "sem i" in s:
        sm = "First Semester"
    elif "second sem" in s or "semester ii" in s or "second semester" in s or "sem ii" in s:
        sm = "Second Semester"
    pt = "4-year" if "new" in s else ("5-year" if "old" in s else None)
    return yr, sm, pt

@router.get("/progress", tags=["student"])
async def get_progress(current_user=Depends(get_current_user)):
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    doc = await col.find_one({"student_id": current_user["user_id"]})
    if not doc:
        try:
            record = await fetch_latest_academic_record(current_user["user_id"])
            derived = _derive_enrollment_year(record)
            program_type = _parse_program_type(derived or "")
            return {
                "student_id": current_user["user_id"],
                "academic_year": derived or "",
                "program_type": program_type,
                "program_rule_note": _program_rule_note(program_type),
            }
        except Exception:
            return {}
    doc["_id"] = str(doc.get("_id"))
    return doc

@router.post("/progress/academic-year", tags=["student"])
async def save_academic_year(payload: dict, current_user=Depends(get_current_user)):
    academic_year = str(payload.get("academic_year", "")).strip()
    if not academic_year:
        raise HTTPException(status_code=422, detail="academic_year is required")
    db = await get_database()
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    entered_norm = _normalize_ay(academic_year)
    existing_norm = _normalize_ay(profile.get("admission_academic_year", ""))
    if existing_norm and existing_norm != entered_norm:
        raise HTTPException(status_code=409, detail="Academic year does not match our records")
    if not existing_norm:
        record = await fetch_latest_academic_record(current_user["user_id"])
        derived = _derive_enrollment_year(record)
        if derived:
            if _normalize_ay(derived) != entered_norm:
                raise HTTPException(status_code=409, detail=f"Academic year does not match our records (expected {derived})")
    program_type = _parse_program_type(academic_year)
    rule_note = _program_rule_note(program_type)
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    await col.update_one(
        {"student_id": current_user["user_id"]},
        {
            "$set": {
                "student_id": current_user["user_id"],
                "academic_year": academic_year,
                "program_type": program_type,
                "program_rule_note": rule_note,
                "updated_at": datetime.utcnow(),
            },
            "$setOnInsert": {"created_at": datetime.utcnow()},
        },
        upsert=True,
    )
    if not existing_norm:
        to_store = _normalize_ay(profile.get("admission_academic_year", "")) or _normalize_ay(academic_year)
        await users.update_one(
            {"user_id": current_user["user_id"]},
            {"$set": {"student_profile.admission_academic_year": to_store}}
        )
    return {"program_type": program_type, "program_rule_note": rule_note}

@router.post("/progress/current", tags=["student"])
async def save_current(payload: dict, current_user=Depends(get_current_user)):
    current_year = str(payload.get("current_year", "")).strip()
    current_semester = str(payload.get("current_semester", "")).strip()
    if not current_year or not current_semester:
        raise HTTPException(status_code=422, detail="current_year and current_semester are required")
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    doc = await col.find_one({"student_id": current_user["user_id"]})
    academic_year = (doc or {}).get("academic_year")
    program_type = (doc or {}).get("program_type")
    if not academic_year or not program_type:
        try:
            record = await fetch_latest_academic_record(current_user["user_id"])
            derived_ay = _derive_enrollment_year(record)
            academic_year = academic_year or derived_ay or ""
            program_type = program_type or _parse_program_type(academic_year)
        except Exception:
            academic_year = academic_year or ""
            program_type = program_type or "4-year"
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    prof_yr, prof_sem, prof_pt = _parse_profile_current(profile.get("current_year"))
    if prof_pt and not program_type:
        program_type = prof_pt
    if prof_yr and prof_yr != current_year:
        raise HTTPException(status_code=409, detail=f"Current year does not match our records (expected {prof_yr}). Please enter the real year and semester.")
    if prof_sem and prof_sem != current_semester:
        raise HTTPException(status_code=409, detail=f"Current semester does not match our records (expected {prof_sem}). Please enter the real year and semester.")
    years, semesters = _valid_options(program_type)
    if current_year not in years or current_semester not in semesters:
        raise HTTPException(status_code=400, detail="Invalid selection for program type")
    await col.update_one(
        {"student_id": current_user["user_id"]},
        {
            "$set": {
                "student_id": current_user["user_id"],
                "academic_year": academic_year,
                "program_type": program_type,
                "current_year": current_year,
                "current_semester": current_semester,
                "program_duration": program_type,
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )
    return {"program_type": program_type, "program_duration": program_type, "current_year": current_year, "current_semester": current_semester}
