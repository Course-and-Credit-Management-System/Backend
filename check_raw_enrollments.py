import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def check_raw_enrollments():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    # Get a specific document to see raw structure
    doc = await db["Enrollments"].find_one({"student_id": "TNT-8789", "course_id": "CS-101"})
    
    if doc:
        import json
        print('Raw document structure:')
        print(json.dumps(doc, default=str, indent=2))
    else:
        print('Document not found')

if __name__ == "__main__":
    asyncio.run(check_raw_enrollments())
