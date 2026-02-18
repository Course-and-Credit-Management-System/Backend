import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def debug_validation():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    # Get the current document
    doc = await db['Enrollments'].find_one({'student_id': 'TNT-2036', 'course_id': 'SE-101'})
    if doc:
        print('Current document:')
        for key, value in doc.items():
            if key != '_id':
                print(f'  {key}: {value}')
        
        # Try to update with a simple change
        try:
            result = await db['Enrollments'].update_one(
                {'_id': doc['_id']},
                {'$set': {'scores': 55.0}}
            )
            print(f'Update result: {result.modified_count} documents modified')
        except Exception as e:
            print(f'Update failed: {e}')
    else:
        print('Document not found')

if __name__ == "__main__":
    asyncio.run(debug_validation())
