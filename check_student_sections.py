import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def check_student_sections():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    try:
        users_col = await _get_col(db, ["Users", "users"])
        
        # Find all students and check their section data
        students = await users_col.find({"role": "student"}).to_list(None)
        
        print(f"Found {len(students)} students:")
        print("-" * 80)
        
        for i, student in enumerate(students[:10]):  # Show first 10 students
            user_id = student.get("user_id", "N/A")
            name = student.get("name", "N/A")
            year = student.get("student_profile", {}).get("current_year", "N/A")
            section = student.get("student_profile", {}).get("section", "N/A")
            
            print(f"{i+1}. {user_id} - {name}")
            print(f"   Year: {year}")
            print(f"   Section: {section}")
            print(f"   Full profile: {student.get('student_profile', {})}")
            print()
            
    except Exception as e:
        print(f"Error: {e}")

async def _get_col(db, names: list):
    cols = await db.list_collection_names()
    for n in names:
        if n in cols:
            return db[n]
    return db[names[0]]

if __name__ == "__main__":
    asyncio.run(check_student_sections())
