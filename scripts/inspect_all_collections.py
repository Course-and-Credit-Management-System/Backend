import asyncio
import os
import sys

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient
from app.models.user import User
from app.models.enrollment import Enrollment
from app.models.course import Course
from beanie import init_beanie

async def main():
    settings = Settings()
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[User, Enrollment, Course]
    )
    
    # 1. Inspect Enrollments
    print("\n--- Enrollment.semesterAttend ---")
    enrollments = await Enrollment.find_all().to_list()
    enr_sems = set()
    for e in enrollments:
        if e.semester_attend:
            enr_sems.add(str(e.semester_attend))
            
    for s in sorted(enr_sems):
        print(f"'{s}'")

    # 2. Inspect Users
    print("\n--- User.student_profile.current_year ---")
    users = await User.find_all().to_list()
    user_sems = set()
    for u in users:
        # Check if student_profile exists and is a dict or model
        if u.role == "student" and u.student_profile:
            # Assuming student_profile is a dict based on recent code reads, or a model
            # In beanie it might be a Pydantic model
            cy = None
            if isinstance(u.student_profile, dict):
                cy = u.student_profile.get("current_year")
            elif hasattr(u.student_profile, "current_year"):
                 cy = u.student_profile.current_year
            
            if cy:
                user_sems.add(str(cy))

    for s in sorted(user_sems):
        print(f"'{s}'")

    # 3. Inspect Courses (Old values check)
    print("\n--- Course.semester (looking for old) ---")
    courses = await Course.find_all().to_list()
    course_sems = set()
    for c in courses:
        if c.semester:
            for item in c.semester:
                val = ""
                if isinstance(item, dict):
                    val = item.get("semester", "")
                else:
                    val = str(item)
                
                if "old" in str(val).lower() or "new" in str(val).lower():
                    course_sems.add(str(val))
    
    for s in sorted(course_sems):
        print(f"'{s}'")

if __name__ == "__main__":
    asyncio.run(main())
