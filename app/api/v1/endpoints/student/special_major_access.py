from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_database
from app.api.v1.deps.auth import get_current_user

router = APIRouter()

# Local helpers (decoupled from existing major_select to keep flows separate)
FOUR_YEAR_MAJORS = ["SE", "KE", "BIS", "CSec", "HPC", "CN", "ES"]
TRACKS = ["CS", "CT"]
TRACK_MAJORS = {
    "CS": ["SE", "KE", "BIS", "CSec"],
    "CT": ["CN", "HPC", "ES"],
}

async def _get_col(db, names: list[str]):
    cols = await db.list_collection_names()
    for n in names:
        if n in cols:
            return db[n]
    return db[names[0]]

def _year_to_num(label: str | None) -> int | None:
    s = (label or "").strip().lower()
    mapping = {
        "first year": 1, "1st year": 1, "year 1": 1,
        "second year": 2, "2nd year": 2, "year 2": 2,
        "third year": 3, "3rd year": 3, "year 3": 3,
        "fourth year": 4, "4th year": 4, "year 4": 4,
        "fifth year": 5, "5th year": 5, "year 5": 5,
    }
    return mapping.get(s)

def _semester_to_num(label: str | None) -> int | None:
    s = (label or "").strip().lower()
    mapping = {
        "first semester": 1, "semester i": 1, "sem i": 1,
        "second semester": 2, "semester ii": 2, "sem ii": 2,
    }
    return mapping.get(s)

def _parse_profile_current_year(raw: str | None):
    s = (raw or "").strip().lower()
    year_num = None
    sem_num = None
    if "1st year" in s or "first year" in s or "year 1" in s:
        year_num = 1
    elif "2nd year" in s or "second year" in s or "year 2" in s:
        year_num = 2
    elif "3rd year" in s or "third year" in s or "year 3" in s:
        year_num = 3
    elif "4th year" in s or "fourth year" in s or "year 4" in s:
        year_num = 4
    elif "5th year" in s or "fifth year" in s or "year 5" in s:
        year_num = 5
    if "first sem" in s or "semester i" in s or "first semester" in s or "sem i" in s:
        sem_num = 1
    elif "second sem" in s or "semester ii" in s or "second semester" in s or "sem ii" in s:
        sem_num = 2
    return year_num, sem_num

def _profile_program_type(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    if not s:
        return None
    if "new" in s:
        return "4-year"
    if "old" in s:
        return "5-year"
    return None

def _derive_program_type(progress_doc: dict, profile: dict) -> str:
    pd = progress_doc.get("program_type")
    if pd in ("4-year", "5-year"):
        return pd
    pd2 = profile.get("program_duration")
    if pd2 in ("4-year", "5-year"):
        return pd2
    pt = _profile_program_type(profile.get("current_year"))
    return pt or "4-year"

def _eligibility_special(program_type: str, ynum: int | None, snum: int | None) -> tuple[bool, str]:
    if ynum is None or snum is None:
        return False, "Current year/semester not set"
    if program_type == "5-year":
        if ynum in (1, 2):
            return True, ""
        if ynum == 3 and snum in (1, 2):  # allow 3rd year both semesters
            return True, ""
        if ynum == 4 and snum == 1:
            return True, ""
        return False, "Not eligible (4th Year – Second Sem or 5th Year)"
    # 4-year (new)
    if ynum in (1, 2):
        return True, ""
    if ynum == 3 and snum == 1:
        return True, ""
    return False, "Not eligible (3rd Year – Second Sem or any 4th Year)"

def _track_from_major(major: str | None) -> str | None:
    if not major:
        return None
    for t, lst in TRACK_MAJORS.items():
        if major in lst:
            return t
    return None

@router.get("/special-major/eligibility", tags=["student"])
async def special_major_eligibility(current_user=Depends(get_current_user)):
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]}) or {}
    ynum = _year_to_num(doc.get("current_year"))
    snum = _semester_to_num(doc.get("current_semester"))
    if ynum is None or snum is None:
        py, ps = _parse_profile_current_year(profile.get("current_year"))
        ynum = ynum if ynum is not None else py
        snum = snum if snum is not None else ps
    program_type = _derive_program_type(doc, profile)
    already = bool(doc.get("selected_major"))
    eligible, reason = _eligibility_special(program_type, ynum, snum)
    return {
        "program_type": program_type,
        "current_year_num": ynum,
        "current_semester_num": snum,
        "eligible": (eligible and not already),
        "already_selected": already,
        "reason": "" if eligible and not already else (reason or "Already selected"),
    }

@router.get("/special-major/options", tags=["student"])
async def special_major_options(current_user=Depends(get_current_user)):
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]}) or {}
    program_type = _derive_program_type(doc, profile)
    track = doc.get("selected_track") or profile.get("major_track")
    if program_type == "4-year":
        majors = FOUR_YEAR_MAJORS
    else:
        t = str(track or "").upper()
        if t in TRACK_MAJORS:
            majors = TRACK_MAJORS[t]
        else:
            # If no track on record, show union of all 5-year majors for special access
            majors = sorted(list({m for lst in TRACK_MAJORS.values() for m in lst}))
    return {"program_type": program_type, "track": track, "majors": majors}

@router.post("/special-major/select", tags=["student"])
async def special_major_select(payload: dict, current_user=Depends(get_current_user)):
    major = str(payload.get("major", "")).strip()
    if not major:
        raise HTTPException(status_code=422, detail="major is required")
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]}) or {}
    ynum = _year_to_num(doc.get("current_year"))
    snum = _semester_to_num(doc.get("current_semester"))
    if ynum is None or snum is None:
        py, ps = _parse_profile_current_year(profile.get("current_year"))
        ynum = ynum if ynum is not None else py
        snum = snum if snum is not None else ps
    program_type = _derive_program_type(doc, profile)
    eligible, reason = _eligibility_special(program_type, ynum, snum)
    if not eligible:
        raise HTTPException(status_code=403, detail=reason or "Not eligible")
    if doc.get("selected_major"):
        raise HTTPException(status_code=400, detail="Already selected")
    track = doc.get("selected_track") or profile.get("major_track") or _track_from_major(major)
    year_label = None
    sem_label = None
    if doc.get("current_year") and doc.get("current_semester"):
        year_label = doc.get("current_year")
        sem_label = doc.get("current_semester")
    else:
        py, ps = _parse_profile_current_year(profile.get("current_year"))
        if py in (1, 2, 3, 4, 5):
            year_label = {1: "First Year", 2: "Second Year", 3: "Third Year", 4: "Fourth Year", 5: "Fifth Year"}[py]
        if ps in (1, 2):
            sem_label = {1: "First Semester", 2: "Second Semester"}[ps]
    updates = {
        "student_id": current_user["user_id"],
        "user_id": current_user["user_id"],
        "selected_major": major,
        "selected_track": track,
        "program_type": program_type,
        "program_duration": program_type,
        "selected_major_at": __import__("datetime").datetime.utcnow(),
        "updated_at": __import__("datetime").datetime.utcnow(),
    }
    if year_label:
        updates["current_year"] = year_label
    if sem_label:
        updates["current_semester"] = sem_label
    if "academic_year" not in doc:
        updates["academic_year"] = ""
    await col.update_one(
        {"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]},
        {"$set": updates},
        upsert=True
    )
    try:
        await users.update_one(
            {"user_id": current_user["user_id"]},
            {"$set": {"student_profile.major_id": major, "student_profile.major_track": track}}
        )
    except Exception:
        pass
    return {"selected_major": major, "selected_track": track, "program_type": program_type}

@router.post("/special-major/populate-from-profile", tags=["student"])
async def special_major_populate_from_profile(current_user=Depends(get_current_user)):
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    major = profile.get("major_id") or ""
    track = (profile.get("major_track") or _track_from_major(major)) or ""
    # derive current year/semester labels from profile.current_year
    ynum, snum = _parse_profile_current_year(profile.get("current_year"))
    year_label = {1: "First Year", 2: "Second Year", 3: "Third Year", 4: "Fourth Year", 5: "Fifth Year"}.get(ynum, "")
    sem_label = {1: "First Semester", 2: "Second Semester"}.get(snum, "")
    # derive program type/duration from Users profile (or fallback rules)
    program_type = _derive_program_type({}, profile)
    program_duration = program_type
    existing = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]}) or {}
    sel_major_at = existing.get("selected_major_at")
    if not sel_major_at and major:
        sel_major_at = __import__("datetime").datetime.utcnow()
    # Always upsert a standardized document with all required keys present,
    # populating from Users when available and leaving others as "".
    updates = {
        "student_id": current_user["user_id"],
        "user_id": current_user["user_id"],
        "academic_year": "",
        "current_semester": sem_label or "",
        "current_year": year_label or "",
        "program_duration": program_duration or "",
        "program_type": program_type or "",
        "selected_major": major or "",
        "selected_track": track or "",
        "selected_major_at": sel_major_at or "",
        "updated_at": __import__("datetime").datetime.utcnow(),
    }
    await col.update_one(
        {"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]},
        {"$set": updates},
        upsert=True
    )
    return {"updated": True, "selected_major": major or "", "selected_track": track or ""}
