"""Admin Student Management endpoints."""
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from pydantic import BaseModel, EmailStr, ValidationError
import io

from app.models.user import User, StudentProfile
from app.api.v1.deps.auth import require_admin, _get_col
from app.models.auth_credential import AuthCredential
from app.models.enums import Role, AcademicStatus, AcademicYear
from app.core.database import get_database
from app.core.security import hash_password

router = APIRouter()

# Request/Response schemas
class StudentCreate(BaseModel):
    user_id: str  # e.g., TNT-8801
    name: str
    email: EmailStr
    major: str  # Major code like CS, SE, CT, etc.
    year: int  # 1-5
    semester: int  # 1-2
    section: Optional[str] = None  # A, B, C for years 1-3
    status: str = "Active"  # Active, Probation, Suspended
    total_credits: int = 0

class StudentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    major: Optional[str] = None
    year: Optional[int] = None
    semester: Optional[int] = None
    section: Optional[str] = None
    status: Optional[str] = None
    total_credits: Optional[int] = None

class StudentResponse(BaseModel):
    id: str
    user_id: str
    name: str
    email: str
    major: str
    year: int
    semester: int
    section: Optional[str] = None
    status: str
    total_credits: int
    required_credits: int = 120

def get_academic_year_enum(year: int, semester: int) -> AcademicYear:
    """Convert year and semester to AcademicYear enum."""
    mapping = {
        (1, 1): AcademicYear.FIRST_YEAR_FIRST_SEM_NEW,
        (1, 2): AcademicYear.FIRST_YEAR_SECOND_SEM_NEW,
        (2, 1): AcademicYear.SECOND_YEAR_FIRST_SEM_NEW,
        (2, 2): AcademicYear.SECOND_YEAR_SECOND_SEM_NEW,
        (3, 1): AcademicYear.THIRD_YEAR_FIRST_SEM_NEW,
        (3, 2): AcademicYear.THIRD_YEAR_SECOND_SEM_NEW,
        (4, 1): AcademicYear.FOURTH_YEAR_FIRST_SEM_NEW,
        (4, 2): AcademicYear.FOURTH_YEAR_SECOND_SEM_NEW,
        (5, 1): AcademicYear.FIFTH_YEAR_FIRST_SEM_OLD,
        (5, 2): AcademicYear.FIFTH_YEAR_SECOND_SEM_OLD,
    }
    return mapping.get((year, semester), AcademicYear.FIRST_YEAR_FIRST_SEM_NEW)

def parse_academic_year(academic_year) -> tuple:
    """Parse AcademicYear enum or string to get year and semester numbers."""
    year_str = academic_year.value if hasattr(academic_year, 'value') else str(academic_year or "")
    year = 1
    semester = 1

    if "5th Year" in year_str or "5th" in year_str:
        year = 5
    elif "4th Year" in year_str or "4th" in year_str:
        year = 4
    elif "3rd Year" in year_str or "3rd" in year_str:
        year = 3
    elif "2nd Year" in year_str or "2nd" in year_str:
        year = 2
    elif "1st Year" in year_str or "1st" in year_str:
        year = 1

    if "Second Sem" in year_str or "2nd Sem" in year_str or "Sem 2" in year_str:
        semester = 2

    return year, semester


@router.get("/", response_model=List[StudentResponse])
async def get_students(
    _admin=Depends(require_admin),
    search: Optional[str] = Query(None, description="Search by name or ID"),
    year: Optional[int] = Query(None, ge=1, le=5, description="Filter by year (1-5)"),
    semester: Optional[int] = Query(None, ge=1, le=2, description="Filter by semester (1-2)"),
    major: Optional[str] = Query(None, description="Filter by major code"),
    section: Optional[str] = Query(None, description="Filter by section (A, B, C)"),
    status: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    """Get list of students with filters. Uses raw MongoDB for reliable data display."""
    db = await get_database()
    users_col = await _get_col(db, ["Users", "users"])
    progress_col = await _get_col(db, ["students_progress", "StudentsProgress"])
    progress_cache = {}

    query = {"role": {"$in": ["student", "Student"]}}
    if search and search.strip():
        search_re = {"$regex": search.strip(), "$options": "i"}
        query["$or"] = [
            {"user_id": search_re},
            {"name": search_re},
            {"email": search_re},
        ]

    cursor = users_col.find(query)
    result = []
    async for doc in cursor:
        try:
            sp = doc.get("student_profile")
            if sp is None:
                sp = {}
            sid = doc.get("user_id") or doc.get("id") or ""

            # Prefer major from students_progress.selected_major when available
            progress_doc = None
            if sid:
                if sid in progress_cache:
                    progress_doc = progress_cache[sid]
                else:
                    progress_doc = await progress_col.find_one(
                        {"student_id": sid},
                        {"selected_major": 1},
                    )
                    progress_cache[sid] = progress_doc or {}

            # Major comes **only** from students_progress.selected_major for the list view
            major_from_progress = str((progress_doc or {}).get("selected_major") or "").strip()

            curr_yr = sp.get("current_year") or "1st Year, First Sem(new)"
            try:
                yr, sem = parse_academic_year(curr_yr)
            except Exception:
                yr, sem = 1, 1

            # Use progress-major only; if empty, show as blank/None
            student_major = major_from_progress
            status_val = sp.get("academic_status") or "Active"
            if hasattr(status_val, "value"):
                status_val = status_val.value
            status_val = str(status_val)
            student_section = sp.get("section")

            if year is not None and yr != year:
                continue
            if semester is not None and sem != semester:
                continue
            if major is not None and student_major != major:
                continue
            if status is not None and status_val != status:
                continue
            if section is not None and student_section != section:
                continue

            result.append(
                StudentResponse(
                    id=str(doc["_id"]),
                    user_id=doc.get("user_id", ""),
                    name=doc.get("name", ""),
                    email=doc.get("email", ""),
                    major=student_major,
                    year=yr,
                    semester=sem,
                    section=student_section,
                    status=status_val,
                    total_credits=int(sp.get("total_credits_completed", sp.get("total_credits", 0)) or 0),
                    required_credits=120,
                )
            )
        except Exception:
            continue

    return result[skip:skip + limit]


@router.post("/", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
@router.post("/create", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(student_data: StudentCreate, _admin=Depends(require_admin)):
    """Create a new student. Uses raw MongoDB for reliability."""
    try:
        return await _do_create_student(student_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create failed: {str(e)[:150]}")


async def _do_create_student(student_data: StudentCreate):
    db = await get_database()
    users_col = await _get_col(db, ["Users", "users"])
    creds_col = await _get_col(db, ["AuthCredentials", "authcredentials"])

    if await users_col.find_one({"user_id": student_data.user_id}):
        raise HTTPException(status_code=400, detail="Student with this ID already exists")
    if await users_col.find_one({"email": student_data.email}):
        raise HTTPException(status_code=400, detail="Email already in use")

    section_val = student_data.section if 1 <= student_data.year <= 3 else None
    current_year_val = get_academic_year_enum(student_data.year, student_data.semester).value
    now = datetime.now(timezone.utc)

    user_doc = {
        "user_id": student_data.user_id,
        "name": student_data.name,
        "email": student_data.email,
        "role": "student",
        "created_at": now,
        "student_profile": {
            "major_id": student_data.major,
            "academic_status": str(student_data.status),
            "total_credits": student_data.total_credits,
            "current_year": current_year_val,
            "gpa": 0.0,
            "cgpa": 0.0,
        },
        "academic_history": [],
        "major_history": [],
    }
    if section_val is not None:
        user_doc["student_profile"]["section"] = section_val
    result = await users_col.insert_one(user_doc, bypass_document_validation=True)
    inserted_id = result.inserted_id

    pwd_hash = hash_password(f"{student_data.user_id}@123")
    await creds_col.insert_one({
        "user_id": student_data.user_id,
        "password_hash": pwd_hash,
        "must_reset_password": True,
        "created_at": now,
        "updated_at": now,
    }, bypass_document_validation=True)

    return StudentResponse(
        id=str(inserted_id),
        user_id=student_data.user_id,
        name=student_data.name,
        email=student_data.email,
        major=student_data.major,
        year=student_data.year,
        semester=student_data.semester,
        section=section_val,
        status=student_data.status,
        total_credits=student_data.total_credits,
        required_credits=120,
    )


@router.post("/import-excel")
async def import_students_from_excel(file: UploadFile = File(...), _admin=Depends(require_admin)):
    """Import students from Excel file. Define before /{student_id} to avoid path conflict."""
    if not file.filename or not file.filename.lower().endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="File must be .xlsx format (Excel 2007+)")

    try:
        import openpyxl
        contents = await file.read()
        wb = openpyxl.load_workbook(io.BytesIO(contents))
        sheet = wb.active

        headers = [str(c.value).strip().lower() if c.value else '' for c in sheet[1]]
        for col in ['user_id', 'name', 'email', 'major', 'year', 'semester']:
            if col not in headers:
                raise HTTPException(status_code=400, detail=f"Missing column: {col}")

        inserted = 0
        skipped = 0
        errors = []

        for row_num, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            try:
                data = dict(zip(headers, row))
                if not data.get('user_id') or not data.get('name'):
                    continue

                user_id = str(data['user_id']).strip()
                name = str(data['name']).strip()
                email = str(data.get('email') or '').strip()
                if not email or '@' not in email:
                    email = f"{user_id.lower().replace('-', '').replace(' ', '')}@uni.edu"
                major = str(data.get('major') or 'CS').strip() or 'CS'
                year = int(float(data.get('year') or 1))
                semester = int(float(data.get('semester') or 1))
                year = max(1, min(5, year))
                semester = max(1, min(2, semester))
                status_raw = str(data.get('status') or 'Active').strip()
                status_map_lower = {"active": "Active", "probation": "Probation", "suspended": "Suspended", "graduated": "Graduated"}
                status_val = status_map_lower.get(status_raw.lower(), "Active")
                total_credits = max(0, int(float(data.get('total_credits') or 0)))
                raw_section = str(data.get('section') or '').strip()
                if raw_section.lower() in ('', 'none', 'no section', '-'):
                    section_val = None
                else:
                    section_val = (raw_section or 'A')[:1].upper()
                    if section_val not in ('A', 'B', 'C'):
                        section_val = 'A' if 1 <= year <= 3 else None

                result = await _create_single_student(
                    user_id, name, email, major, year, semester, status_val, total_credits, section_val
                )
                if result == "created":
                    inserted += 1
                else:
                    skipped += 1
            except ValidationError as ve:
                errors.append(f"Row {row_num}: Validation - {str(ve)[:120]}")
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)[:80]}")

        return {
            "success": True,
            "inserted": inserted,
            "updated": 0,
            "skipped": skipped,
            "errors": errors[:5],
            "error_details": errors[:5]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:100])


@router.put("/{student_id}", response_model=StudentResponse)
@router.post("/{student_id}/update", response_model=StudentResponse)
async def update_student(student_id: str, student_update: StudentUpdate, _admin=Depends(require_admin)):
    """Update a student by user_id. Uses raw MongoDB for reliability."""
    try:
        return await _do_update_student(student_id, student_update)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)[:150]}")


async def _do_update_student(student_id: str, student_update: StudentUpdate):
    db = await get_database()
    users_col = await _get_col(db, ["Users", "users"])
    user_doc = await users_col.find_one({"user_id": student_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="Student not found")
    if str(user_doc.get("role") or "").lower() != "student":
        raise HTTPException(status_code=400, detail="User is not a student")

    update_data = student_update.model_dump(exclude_unset=True)
    if not update_data:
        update_data = student_update.model_dump()

    set_updates = {}
    sp = user_doc.get("student_profile") or {}
    sp = dict(sp)

    if "name" in update_data:
        set_updates["name"] = update_data["name"]
    if "email" in update_data:
        existing = await users_col.find_one({"email": update_data["email"]})
        if existing and existing.get("user_id") != student_id:
            raise HTTPException(status_code=400, detail="Email already in use")
        set_updates["email"] = update_data["email"]
    if "major" in update_data:
        sp["major_id"] = update_data["major"]
    if "section" in update_data:
        curr = sp.get("current_year")
        yr = update_data.get("year")
        if yr is None and curr:
            try:
                yr = parse_academic_year(curr)[0]
            except Exception:
                yr = 1
        sp["section"] = update_data["section"] if 1 <= (yr or 1) <= 3 else None
    if "year" in update_data or "semester" in update_data:
        curr = sp.get("current_year")
        if curr:
            try:
                pyr, psem = parse_academic_year(curr)
            except Exception:
                pyr, psem = 1, 1
        else:
            pyr, psem = 1, 1
        yr = update_data.get("year") or pyr
        sem = update_data.get("semester") or psem
        sp["current_year"] = get_academic_year_enum(yr, sem).value
    if "status" in update_data:
        sp["academic_status"] = str(update_data["status"])
    if "total_credits" in update_data:
        val = int(update_data["total_credits"]) if update_data["total_credits"] is not None else 0
        sp["total_credits"] = val
        sp["total_credits_completed"] = val  # list view reads this

    if sp:
        set_updates["student_profile"] = sp
    if set_updates:
        await users_col.update_one(
            {"user_id": student_id},
            {"$set": set_updates},
            bypass_document_validation=True,
        )

    updated = await users_col.find_one({"user_id": student_id})
    sp = updated.get("student_profile") or {}
    curr_yr = sp.get("current_year") or "1st Year, First Sem(new)"
    try:
        yr, sem = parse_academic_year(curr_yr)
    except Exception:
        yr, sem = 1, 1
    status_val = sp.get("academic_status") or "Active"
    if hasattr(status_val, "value"):
        status_val = status_val.value
    return StudentResponse(
        id=str(updated["_id"]),
        user_id=updated["user_id"],
        name=updated.get("name", ""),
        email=updated.get("email", ""),
        major=sp.get("major_id", "CS"),
        year=yr,
        semester=sem,
        section=sp.get("section"),
        status=str(status_val),
        total_credits=sp.get("total_credits", 0),
        required_credits=120,
    )



async def _do_delete_student(student_id: str):
    """Shared delete logic for DELETE and POST delete."""
    db = await get_database()
    users_col = await _get_col(db, ["Users", "users"])
    user_doc = await users_col.find_one({"user_id": student_id})
    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found"
        )
    role_val = user_doc.get("role") or ""
    if str(role_val).lower() != "student":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a student"
        )
    creds = await _get_col(db, ["AuthCredentials", "authcredentials"])
    await creds.delete_many({"user_id": student_id})
    result = await users_col.delete_one({"user_id": student_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=500, detail="Failed to delete user record")
    return None


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(student_id: str, _admin=Depends(require_admin)):
    """Delete a student by user_id."""
    return await _do_delete_student(student_id)


@router.post("/{student_id}/delete", status_code=status.HTTP_200_OK)
async def delete_student_post(student_id: str, _admin=Depends(require_admin)):
    """Alternative delete via POST (avoids CORS preflight issues with DELETE)."""
    try:
        await _do_delete_student(student_id)
        return {"success": True, "message": "Student deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)[:200]}")


async def _create_single_student(user_id: str, name: str, email: str, major: str, year: int, semester: int, status_val: str, total_credits: int, section_val: Optional[str] = None):
    """Helper function to create a single student - uses raw MongoDB like _do_create_student."""
    db = await get_database()
    users_col = await _get_col(db, ["Users", "users"])
    creds_col = await _get_col(db, ["AuthCredentials", "authcredentials"])

    if await users_col.find_one({"user_id": user_id}):
        return "exists"
    if await users_col.find_one({"email": email}):
        return "skipped"  # email already used

    section = section_val if 1 <= year <= 3 and section_val in ("A", "B", "C") else None
    current_year_val = get_academic_year_enum(year, semester).value
    now = datetime.now(timezone.utc)

    user_doc = {
        "user_id": user_id,
        "name": name,
        "email": email,
        "role": "student",
        "created_at": now,
        "student_profile": {
            "major_id": major,
            "academic_status": str(status_val),
            "total_credits": total_credits,
            "total_credits_completed": total_credits,
            "current_year": current_year_val,
            "gpa": 0.0,
            "cgpa": 0.0,
        },
        "academic_history": [],
        "major_history": [],
    }
    if section is not None:
        user_doc["student_profile"]["section"] = section

    await users_col.insert_one(user_doc, bypass_document_validation=True)
    await creds_col.insert_one({
        "user_id": user_id,
        "password_hash": hash_password(f"{user_id}@123"),
        "must_reset_password": True,
        "created_at": now,
        "updated_at": now,
    }, bypass_document_validation=True)

    return "created"
