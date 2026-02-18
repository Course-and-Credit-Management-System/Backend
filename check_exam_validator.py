import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def check_validator():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    collections_cursor = await db.list_collections()
    collections_info = await collections_cursor.to_list(length=None)
    exam_col_info = next((c for c in collections_info if c['name'] in ['ExamResults', 'exam_results']), None)
    
    if exam_col_info:
        print(f'Collection: {exam_col_info["name"]}')
        options = exam_col_info.get('options', {})
        validator = options.get('validator', {})
        if validator:
            import json
            print('Validator found:')
            print(json.dumps(validator, default=str, indent=2))
        else:
            print('No validator found')
    else:
        print('ExamResults collection not found')

if __name__ == "__main__":
    asyncio.run(check_validator())
