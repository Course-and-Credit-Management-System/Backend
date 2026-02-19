import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def check_duplicates():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    docs = await db['Enrollments'].find({'student_id': 'TNT-2036', 'course_id': 'SE-101'}).to_list(None)
    print(f'Found {len(docs)} records for TNT-2036 SE-101:')
    for i, doc in enumerate(docs):
        print(f'  Record {i+1}: semesterAttend="{doc.get("semesterAttend")}", scores={doc.get("scores")}, is_retake={doc.get("is_retake")}')

if __name__ == "__main__":
    asyncio.run(check_duplicates())
