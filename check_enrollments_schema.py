import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def check_enrollments_schema():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    collections_cursor = await db.list_collections()
    collections_info = await collections_cursor.to_list(length=None)
    enroll_col_info = next((c for c in collections_info if c['name'] in ['Enrollments', 'enrollments']), None)
    
    if not enroll_col_info:
        print('Enrollments collection not found')
        return
        
    col_name = enroll_col_info["name"]
    print(f'Examining collection: {col_name}')
    
    # Get a sample document to understand the structure
    sample_doc = await db[col_name].find_one()
    if sample_doc:
        import json
        print('Sample document structure:')
        print(json.dumps(sample_doc, default=str, indent=2))
        
        # Check if is_retake field exists
        if 'is_retake' in sample_doc:
            print(f'is_retake field found: {sample_doc["is_retake"]}')
        else:
            print('is_retake field not found in sample document')
    else:
        print('No documents found in Enrollments collection')
    
    # Also check the validator if it exists
    options = enroll_col_info.get('options', {})
    validator = options.get('validator', {})
    if validator:
        print('\nCollection validator:')
        print(json.dumps(validator, default=str, indent=2))
    else:
        print('\nNo validator found on Enrollments collection')

if __name__ == "__main__":
    asyncio.run(check_enrollments_schema())
