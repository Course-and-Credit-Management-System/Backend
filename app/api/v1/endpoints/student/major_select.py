from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_database
from app.api.v1.deps.auth import get_current_user

router = APIRouter()

async def _get_col(db, names: list[str]):
    cols = await db.list_collection_names()
    for n in names:
        if n in cols:
            return db[n]
    return db[names[0]]

FOUR_YEAR_MAJORS = ["SE", "KE", "BIS", "CSec", "HPC", "CN", "ES"]
TRACKS = ["CS", "CT"]
TRACK_MAJORS = {
    "CS": ["SE", "KE", "BIS"],
    "CT": ["CSec"],
}

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

def _parse_profile_current_year(raw: str | None) -> tuple[int | None, int | None, str | None, str | None]:
    s = (raw or "").strip().lower()
    if not s:
        return None, None, None, None
    # Examples observed:
    # "1st Year, First Sem(new)" , "Third Year, First Semester", "4th Year, Second Sem"
    year_num = None
    sem_num = None
    year_label = None
    sem_label = None
    if "1st year" in s or "first year" in s or "year 1" in s:
        year_num = 1
        year_label = "First Year"
    elif "2nd year" in s or "second year" in s or "year 2" in s:
        year_num = 2
        year_label = "Second Year"
    elif "3rd year" in s or "third year" in s or "year 3" in s:
        year_num = 3
        year_label = "Third Year"
    elif "4th year" in s or "fourth year" in s or "year 4" in s:
        year_num = 4
        year_label = "Fourth Year"
    elif "5th year" in s or "fifth year" in s or "year 5" in s:
        year_num = 5
        year_label = "Fifth Year"
    if "first sem" in s or "semester i" in s or "first semester" in s or "sem i" in s:
        sem_num = 1
        sem_label = "First Semester"
    elif "second sem" in s or "semester ii" in s or "second semester" in s or "sem ii" in s:
        sem_num = 2
        sem_label = "Second Semester"
    return year_num, sem_num, year_label, sem_label

def _profile_program_type(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    if not s:
        return None
    if "new" in s:
        return "4-year"
    if "old" in s:
        return "5-year"
    return None

def _validate_major(program_type: str, track: str | None, major: str):
    if program_type == "4-year":
        return major in FOUR_YEAR_MAJORS
    if program_type == "5-year":
        if not track or track not in TRACKS:
            return False
        return major in TRACK_MAJORS.get(track, [])
    return False

def _compute_eligibility(doc: dict) -> dict:
    prof_raw = doc.get("__profile_current_year_raw")
    prof_pt = _profile_program_type(prof_raw)
    prof_pd = doc.get("__profile_program_duration")
    program_type = doc.get("program_type") or (prof_pd if prof_pd in ("4-year", "5-year") else None) or prof_pt or "4-year"
    ynum = _year_to_num(doc.get("current_year"))
    snum = _semester_to_num(doc.get("current_semester"))
    track = doc.get("selected_track") or doc.get("__profile_major_track")
    has_major = bool(doc.get("selected_major"))
    access_ok = bool(doc.get("major_access_approved"))
    # Fallback: derive from Users.student_profile.current_year if missing
    if ynum is None or snum is None:
        py, ps, yl, sl = _parse_profile_current_year(prof_raw)
        if ynum is None and py is not None:
            ynum = py
            doc["current_year"] = yl or doc.get("current_year")
        if snum is None and ps is not None:
            snum = ps
            doc["current_semester"] = sl or doc.get("current_semester")
    # Strict validation: entered year/semester must match Users profile labels if available
    py, ps, yl, sl = _parse_profile_current_year(prof_raw)
    reason = ""
    can_select_track = False
    can_select_major = False
    major_locked = False
    track_required = program_type == "5-year"

    if ynum is None or snum is None:
        return {
            "program_type": program_type,
            "current_year_num": ynum,
            "current_semester_num": snum,
            "track_required": track_required,
            "can_select_track": False,
            "can_select_major": False,
            "major_locked": False,
            "reason": "Current year/semester not set",
        }

    # If Users has canonical current year/semester labels, enforce equality
    if yl and sl:
        if (doc.get("current_year") and doc.get("current_year") != yl) or (doc.get("current_semester") and doc.get("current_semester") != sl):
            return {
                "program_type": program_type,
                "current_year_num": ynum,
                "current_semester_num": snum,
                "track_required": track_required,
                "can_select_track": False,
                "can_select_major": False,
                "major_locked": bool(has_major),
                "reason": "Entered year and semester are incorrect. Please enter the real academic information.",
                "allowed_majors": [],
            }

    if program_type == "4-year":
        if ynum <= 2:
            can_select_major = False
            major_locked = True
            reason = "First and second year students cannot choose major."
        elif ynum == 3:
            if snum == 1:
                can_select_major = not has_major  # allow once
                major_locked = has_major
                reason = "Major selection is no longer available." if has_major else ""
            else:
                can_select_major = False
                major_locked = True if has_major else False
                reason = "Major selection is not allowed."
        else:
            can_select_major = False
            major_locked = True
            reason = "Major selection is no longer available."
        can_select_track = False
    else:  # 5-year
        # Track selection rule: allowed in 3rd Year (both semesters) only
        if ynum == 3:
            can_select_track = True
        else:
            can_select_track = False
        # Major selection rule for 5-year:
        # - 1st & 2nd Year: not allowed
        # - 3rd Year (both semesters): not allowed
        # - 4th Year – First Semester: allowed if track is selected and major not selected yet
        # - Others: not allowed; locked if already selected
        if ynum <= 3:
            can_select_major = False
            # Explicitly lock UI for Year 1–2
            if ynum <= 2:
                major_locked = True
                reason = "First and second year students cannot choose major."
            else:
                reason = "Main major selection is not allowed in this period."
        elif ynum == 4:
            if snum == 1:
                can_select_major = bool(track) and not has_major
                major_locked = has_major
                if not track:
                    reason = "Select track (CS/CT) first"
                elif has_major:
                    reason = "Major selection is no longer available."
                else:
                    reason = ""
            else:
                can_select_major = False
                major_locked = True if has_major else False
                reason = "Major selection is no longer available."
        else:  # 5th year
            can_select_major = False
            major_locked = True if has_major else False
            reason = "Major selection is no longer available."

    allowed_majors = []
    if can_select_major:
        if program_type == "4-year":
            allowed_majors = FOUR_YEAR_MAJORS
        else:
            if track:
                allowed_majors = TRACK_MAJORS.get(track, [])

    return {
        "program_type": program_type,
        "current_year_num": ynum,
        "current_semester_num": snum,
        "track_required": track_required,
        "can_select_track": can_select_track,
        "can_select_major": can_select_major,
        "major_locked": major_locked,
        "reason": reason,
        "allowed_majors": allowed_majors,
    }

def _status_from_eligibility(elig: dict, doc: dict) -> str:
    if doc.get("selected_major") and elig.get("major_locked"):
        return "Already Selected (Locked)"
    if elig.get("can_select_major"):
        return "Available for Major Selection"
    if elig.get("track_required") and not doc.get("selected_track") and elig.get("can_select_track"):
        return "Track Selection Required"
    return "Not Available"

@router.get("/major/state", tags=["student"])
async def major_state(current_user=Depends(get_current_user)):
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]})
    if not doc:
        raise HTTPException(status_code=404, detail="Progress not found")
    # Merge profile data
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    doc["__profile_current_year_raw"] = profile.get("current_year")
    doc["__profile_program_duration"] = profile.get("program_duration")
    doc["__profile_major_track"] = profile.get("major_track")
    state = {
        "program_type": doc.get("program_type"),
        "academic_year": doc.get("academic_year"),
        "current_year": doc.get("current_year"),
        "current_semester": doc.get("current_semester"),
        "selected_track": doc.get("selected_track"),
        "selected_major": doc.get("selected_major"),
        "profile_major_id": profile.get("major_id"),
        "profile_major_track": profile.get("major_track"),
    }
    elig = _compute_eligibility(doc)
    return {**state, **elig, "status": _status_from_eligibility(elig, doc)}

@router.get("/major/options", tags=["student"])
async def major_options(current_user=Depends(get_current_user)):
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]})
    if not doc:
        raise HTTPException(status_code=404, detail="Progress not found")
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    doc["__profile_current_year_raw"] = profile.get("current_year")
    doc["__profile_major_track"] = profile.get("major_track")
    elig = _compute_eligibility(doc)
    effective_track = doc.get("selected_track") or profile.get("major_track")
    if elig["track_required"] and not effective_track:
        return {"type": "tracks", "tracks": TRACKS, "eligibility": elig, "status": _status_from_eligibility(elig, doc)}
    return {"type": "majors", "track": effective_track, "majors": elig.get("allowed_majors", []), "eligibility": elig, "status": _status_from_eligibility(elig, doc)}

@router.get("/major/eligibility", tags=["student"])
async def major_eligibility(current_user=Depends(get_current_user)):
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]})
    if not doc:
        raise HTTPException(status_code=404, detail="Progress not found")
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    doc["__profile_current_year_raw"] = profile.get("current_year")
    elig = _compute_eligibility(doc)
    return {**elig, "status": _status_from_eligibility(elig, doc)}

@router.post("/major/track", tags=["student"])
async def select_track(payload: dict, current_user=Depends(get_current_user)):
    track = str(payload.get("track", "")).upper()
    if track not in TRACKS:
        raise HTTPException(status_code=422, detail="Invalid track")
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]})
    if not doc:
        raise HTTPException(status_code=404, detail="Progress not found")
    if doc.get("program_type") != "5-year":
        raise HTTPException(status_code=400, detail="Track selection only for 5-year program")
    # Enforce year/semester match against Users profile before allowing track selection
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    py, ps, yl, sl = _parse_profile_current_year(profile.get("current_year"))
    if yl and sl and ((doc.get("current_year") and doc.get("current_year") != yl) or (doc.get("current_semester") and doc.get("current_semester") != sl)):
        raise HTTPException(status_code=409, detail="Entered year and semester are incorrect. Please enter the real academic information.")
    elig = _compute_eligibility(doc)
    if not elig.get("can_select_track"):
        raise HTTPException(status_code=403, detail=elig.get("reason") or "Track selection is not allowed now")
    # Dynamic rules:
    # - 3rd Year (both semesters): allow selecting/changing track; always update Users.major_track
    # - 4th Year, First Semester: require track match with Users.major_track if present
    expected_track = str((profile.get("Major_trak") or profile.get("major_track") or "")).upper()
    ynum = elig.get("current_year_num")
    snum = elig.get("current_semester_num")
    if ynum == 4 and snum == 1 and expected_track in TRACKS and track != expected_track:
        raise HTTPException(status_code=409, detail="Entered track major is incorrect. Please enter the real user track major.")
    # Update progress and clear any previously selected major
    updates = {
        "student_id": current_user["user_id"],
        "user_id": current_user["user_id"],
        "selected_track": track,
        "selected_major": None,
        "program_type": doc.get("program_type") or "5-year",
        "program_duration": doc.get("program_type") or "5-year",
        "updated_at": __import__("datetime").datetime.utcnow(),
    }
    if not doc.get("academic_year"):
        updates["academic_year"] = ""
    if not doc.get("current_year") or not doc.get("current_semester"):
        if yl:
            updates["current_year"] = yl
        if sl:
            updates["current_semester"] = sl
    await col.update_one(
        {"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]},
        {"$set": updates},
        upsert=True
    )
    # Always persist selected track to Users profile in 3rd Year or when not set
    try:
        if ynum == 3 or not expected_track:
            await users.update_one(
                {"user_id": current_user["user_id"]},
                {"$set": {"student_profile.major_track": track}}
            )
    except Exception:
        pass
    return {"selected_track": track}

@router.post("/major/select", tags=["student"])
async def select_major(payload: dict, current_user=Depends(get_current_user)):
    major = str(payload.get("major", "")).strip()
    if not major:
        raise HTTPException(status_code=422, detail="major is required")
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]})
    if not doc:
        raise HTTPException(status_code=404, detail="Progress not found")
    program_type = doc.get("program_type") or "4-year"
    # effective track: prefer StudentsProgress selected_track, fallback to Users profile major_track
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    track = doc.get("selected_track") or profile.get("major_track")
    # Derive track from selected major if missing for 5-year 4Y1 selection flows
    if program_type == "5-year" and not track:
        for t, lst in TRACK_MAJORS.items():
            if major in lst:
                track = t
                break
    # Ensure eligibility sees the derived track
    if track and not doc.get("selected_track"):
        doc["selected_track"] = track
    # Enforce year/semester match against Users profile before allowing major selection
    users = await _get_col(db, ["Users", "users"])
    udoc = await users.find_one({"user_id": current_user["user_id"]})
    profile = (udoc or {}).get("student_profile") or {}
    py, ps, yl, sl = _parse_profile_current_year(profile.get("current_year"))
    if yl and sl and ((doc.get("current_year") and doc.get("current_year") != yl) or (doc.get("current_semester") and doc.get("current_semester") != sl)):
        raise HTTPException(status_code=409, detail="Entered year and semester are incorrect. Please enter the real academic information.")
    elig = _compute_eligibility(doc)
    if not elig.get("can_select_major"):
        raise HTTPException(status_code=403, detail=elig.get("reason") or "Major selection is locked")
    if doc.get("selected_major"):
        raise HTTPException(status_code=400, detail="Major selection is no longer available.")
    if not _validate_major(program_type, track, major):
        raise HTTPException(status_code=400, detail="Invalid major for program/track")
    year_label = doc.get("current_year")
    sem_label = doc.get("current_semester")
    if not year_label or not sem_label:
        py2, ps2, yl2, sl2 = _parse_profile_current_year(profile.get("current_year"))
        if yl2 and not year_label:
            year_label = yl2
        if sl2 and not sem_label:
            sem_label = sl2
    updates = {
        "student_id": current_user["user_id"],
        "user_id": current_user["user_id"],
        "selected_major": major,
        "selected_major_at": __import__("datetime").datetime.utcnow(),
        "program_type": program_type,
        "program_duration": program_type,
        "selected_track": track,
        "updated_at": __import__("datetime").datetime.utcnow(),
    }
    if not doc.get("academic_year"):
        updates["academic_year"] = ""
    if year_label:
        updates["current_year"] = year_label
    if sem_label:
        updates["current_semester"] = sem_label
    await col.update_one(
        {"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]},
        {"$set": updates},
        upsert=True
    )
    try:
        eff_track = track
        if not eff_track:
            for t, lst in TRACK_MAJORS.items():
                if major in lst:
                    eff_track = t
                    break
        await users.update_one(
            {"user_id": current_user["user_id"]},
            {"$set": {"student_profile.major_id": major, "student_profile.major_track": eff_track}}
        )
    except Exception:
        pass
    return {"selected_major": major, "program_duration": program_type, "selected_track": track, "message": "Major selected and permanently locked."}

@router.post("/major/access-approve", tags=["student"])
async def approve_access(current_user=Depends(get_current_user)):
    db = await get_database()
    col = await _get_col(db, ["StudentsProgress", "students_progress"])
    doc = await col.find_one({"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]})
    if not doc:
        raise HTTPException(status_code=404, detail="Progress not found")
    await col.update_one(
        {"$or": [{"student_id": current_user["user_id"]}, {"user_id": current_user["user_id"]}]},
        {"$set": {"major_access_approved": True, "updated_at": __import__("datetime").datetime.utcnow()}},
        upsert=True
    )
    return {"major_access_approved": True}
