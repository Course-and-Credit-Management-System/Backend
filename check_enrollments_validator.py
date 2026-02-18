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
    
    try:
        # Get collection info with validator
        collections = await db.list_collections().to_list(None)
        for coll in collections:
            if coll['name'] == 'Enrollments':
                print('Enrollments collection validator:')
                print(coll.get('options', {}).get('validator', {}))
                break
        else:
            print('Enrollments collection not found')
    except Exception as e:
        print(f'Error: {e}')

if __name__ == "__main__":
    asyncio.run(check_validator())
