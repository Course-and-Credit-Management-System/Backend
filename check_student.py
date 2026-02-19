import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def check_student():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    doc = await db['Enrollments'].find_one({'student_id': 'TNT-2036', 'course_id': 'SE-101'})
    if doc:
        print(f'Student: TNT-2036')
        print(f'Course: SE-101')
        print(f'SemesterAttend: {doc.get("semesterAttend")}')
        print(f'Scores: {doc.get("scores")}')
        print(f'is_retake: {doc.get("is_retake")}')
    else:
        print('Document not found')

if __name__ == "__main__":
    asyncio.run(check_student())
