"""
Migration script: Add missing student_profile fields to existing students.
Run this if Major, Year/Sem, Total Credits, Status show empty for existing students.

Usage (from Backend directory): python scripts/fix_student_profiles.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    from app.core.config import get_settings

    settings = get_settings()
    url = settings.MONGODB_URL
    db_name = settings.MONGODB_DB_NAME
    if not url:
        print("ERROR: MONGODB_URL not set in .env")
        return

    client = AsyncIOMotorClient(url)
    db = client[db_name]
    col_names = await db.list_collection_names()
    if "Users" in col_names:
        users_col = db["Users"]
    elif "users" in col_names:
        users_col = db["users"]
    else:
        print(f"ERROR: No Users collection. Found: {col_names}")
        return
    print(f"Using collection: {users_col.name}, database: {db_name}")

    # Match students - case-insensitive role
    students = await users_col.find({"role": {"$regex": r"^student$", "$options": "i"}}).to_list(length=None)
    if len(students) == 0:
        all_docs = await users_col.find({}).limit(10).to_list(length=10)
        roles_seen = list({d.get("role") for d in all_docs})
        print(f"No students found. Sample roles in collection: {roles_seen}")
    print(f"Found {len(students)} student(s)")

    updated = 0
    for i, doc in enumerate(students):
        user_id = doc.get("user_id", "?")
        sp = doc.get("student_profile")
        if i == 0:
            print(f"Sample student_profile for first doc: {sp}")
        if sp is None:
            sp = {}
        else:
            sp = dict(sp)

        # Add student_profile if missing, or fill in missing fields
        needs_update = False
        new_sp = dict(sp) if sp else {}

        if not new_sp.get("major_id"):
            new_sp["major_id"] = "CS"
            needs_update = True
        if not new_sp.get("current_year"):
            new_sp["current_year"] = "1st Year, First Sem(new)"
            needs_update = True
        if not new_sp.get("academic_status"):
            new_sp["academic_status"] = "Active"
            needs_update = True
        if "total_credits" not in new_sp or new_sp.get("total_credits") is None:
            new_sp["total_credits"] = 0
            needs_update = True
        if "gpa" not in new_sp:
            new_sp["gpa"] = 0.0
        if "cgpa" not in new_sp:
            new_sp["cgpa"] = 0.0

        # Update if student_profile was empty, missing, or had gaps
        will_update = needs_update or doc.get("student_profile") is None
        if will_update:
            try:
                await users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"student_profile": new_sp}},
                    bypass_document_validation=True,
                )
                updated += 1
                print(f"  Updated: {user_id}")
            except Exception as e:
                print(f"  Failed {user_id}: {e}")
        else:
            print(f"  Skip {user_id}: profile already complete")

    print(f"\nDone. Updated {updated} student(s).")


if __name__ == "__main__":
    asyncio.run(main())
