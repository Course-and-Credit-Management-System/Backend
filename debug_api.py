import asyncio
import sys
import os
import json

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient
from app.schemas.exam_result import ExamResultUpsertIn
from app.services.grading_service import score_to_grade

async def debug_api():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    # Simulate the API call
    payload = {
        "student_id": "TNT-2036",
        "course_code": "SE-101",
        "year": 1,
        "semester": 1,
        "section": None,
        "major": None,
        "exam_score": 55
    }
    
    print(f'Input payload: {payload}')
    
    # Validate payload
    try:
        validated_payload = ExamResultUpsertIn(**payload)
        print(f'Validated payload: {validated_payload}')
    except Exception as e:
        print(f'Validation failed: {e}')
        return
    
    # Calculate grade
    grade, grade_point, status = score_to_grade(validated_payload.exam_score)
    print(f'Calculated: grade={grade}, grade_point={grade_point}, status={status}')
    
    # Map "Probation" status to "Failed" for Enrollments collection compatibility
    if status == "Probation":
        status = "Failed"
        print(f'Mapped Probation to Failed')
    
    # Create semesterAttend
    year_map = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
    sem_map = {1: "First", 2: "Second"}
    year_str = year_map.get(validated_payload.year, f"{validated_payload.year}th")
    sem_str = sem_map.get(validated_payload.semester, f"{validated_payload.semester}")
    semester_attend = f"{year_str} Year. {sem_str} Sem"
    print(f'semesterAttend: "{semester_attend}"')
    
    # Create document
    doc = {
        "student_id": validated_payload.student_id,
        "course_id": validated_payload.course_code,
        "semesterAttend": semester_attend,
        "status": status,
        "grade": grade,
        "points": grade_point,
        "scores": validated_payload.exam_score,
        "is_retake": status == "Failed",
    }
    
    print(f'Document to update: {doc}')
    
    # Try to find existing record
    existing_doc = await db['Enrollments'].find_one({
        "student_id": validated_payload.student_id,
        "course_id": validated_payload.course_code
    })
    
    if existing_doc:
        print(f'Found existing record with semesterAttend: "{existing_doc.get("semesterAttend")}"')
        
        # Update logic
        current_is_retake = existing_doc.get("is_retake", False)
        new_is_retake = current_is_retake or (status == "Failed")
        doc["is_retake"] = new_is_retake
        
        print(f'Updating with is_retake: {new_is_retake}')
        
        try:
            res = await db['Enrollments'].update_one(
                {"_id": existing_doc["_id"]},
                {"$set": doc}
            )
            print(f'Update successful: {res.modified_count} documents modified')
        except Exception as e:
            print(f'Update failed: {e}')
    else:
        print('No existing record found')

if __name__ == "__main__":
    asyncio.run(debug_api())
