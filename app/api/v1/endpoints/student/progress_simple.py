"""Simple progress endpoint for testing."""
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

@router.get("/progress")
async def get_degree_progress(current_user=Depends(get_current_user)):
    """
    Calculate student's degree progress percentage.
    """
    print("PROGRESS SIMPLE: Endpoint called!")
    
    if current_user.get("role") != "student":
        raise HTTPException(status_code=403, detail="Student access required")
    
    student_id = current_user.get("user_id")
    print(f"PROGRESS SIMPLE: Student ID: {student_id}")
    
    db = await get_database()
    
    # Get collections
    courses_col = await _get_col(db, ["Courses", "courses"])
    
    # Get all courses and categorize them
    all_courses = []
    async for course in courses_col.find({}):
        all_courses.append(course)
    
    # Separate core and elective courses
    core_courses = [c for c in all_courses if c.get("type", "").lower() == "core"]
    elective_courses = [c for c in all_courses if c.get("type", "").lower() == "elective"]
    
    # Use academic_history from user data
    academic_history = current_user.get("academic_history", [])
    passed_enrollments = []
    
    # Convert academic_history entries to enrollment-like format
    for course_entry in academic_history:
        if course_entry.get("status") in ["Completed", "Passed"]:
            passed_enrollments.append({
                "course_id": course_entry.get("course_id"),
                "course_code": course_entry.get("course_code"),
                "status": course_entry.get("status"),
                "grade": course_entry.get("grade"),
                "credits": course_entry.get("credits")
            })
    
    # Get passed course IDs
    passed_course_ids = []
    for enrollment in passed_enrollments:
        course_id = enrollment.get("course_id") or enrollment.get("course_code")
        if course_id:
            passed_course_ids.append(course_id)
    
    # Count completed courses by type
    completed_core = 0
    completed_elective = 0
    
    for course_id in passed_course_ids:
        # Find the course to determine its type
        course = None
        for c in all_courses:
            if (c.get("course_code") == course_id or 
                c.get("_id") == course_id):
                course = c
                break
        
        if course:
            if course.get("type", "").lower() == "core":
                completed_core += 1
            elif course.get("type", "").lower() == "elective":
                completed_elective += 1
    
    # Calculate percentages
    total_core = len(core_courses)
    total_elective = len(elective_courses)
    total_courses = total_core + total_elective
    
    core_percentage = (completed_core / total_core * 100) if total_core > 0 else 0
    elective_percentage = (completed_elective / total_elective * 100) if total_elective > 0 else 0
    overall_percentage = ((completed_core + completed_elective) / total_courses * 100) if total_courses > 0 else 0
    
    result = {
        "student_id": student_id,
        "total_courses": {
            "core": total_core,
            "elective": total_elective,
            "overall": total_courses
        },
        "completed_courses": {
            "core": completed_core,
            "elective": completed_elective,
            "overall": completed_core + completed_elective
        },
        "progress_percentage": {
            "core": round(core_percentage, 2),
            "elective": round(elective_percentage, 2),
            "overall": round(overall_percentage, 2)
        },
        "passed_course_details": passed_enrollments
    }
    
    print(f"PROGRESS SIMPLE: Result: {result}")
    return result
