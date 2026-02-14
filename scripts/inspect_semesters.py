import asyncio
import os
import sys

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient
from app.models.course import Course
from beanie import init_beanie

async def main():
    # Load config manually or from env
    # Since we are running as script, env vars might be needed unless we rely on pydantic-settings reading .env automatically
    # Pydantic Settings reads .env if python-dotenv is installed usually.
    
    settings = Settings() 
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[Course]
    )
    
    print("Fetching courses...")
    courses = await Course.find_all().to_list()
    
    print(f"Total courses: {len(courses)}")
    
    unique_semesters = set()
    for c in courses:
        if c.semester:
            for s in c.semester:
                # s is Dict or similar? In model it says List[Dict[str, Any]]
                # but let's see what we actually have
                if isinstance(s, dict):
                    unique_semesters.add(str(s.get("semester")))
                else:
                     unique_semesters.add(str(s))
                    
    print("\n--- Unique Semester Values ---")
    for s in sorted(unique_semesters):
        print(f"'{s}'")

if __name__ == "__main__":
    asyncio.run(main())
