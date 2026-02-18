import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def check_existing():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    doc = await db['Enrollments'].find_one({'student_id': 'TNT-8801', 'course_id': 'CS-101'})
    if doc:
        print(f'Existing semesterAttend: {doc.get("semesterAttend")}')
    else:
        print('No existing document found')

if __name__ == "__main__":
    asyncio.run(check_existing())
