"""
Migration: Remove 'major_id' from Users.student_profile for all users.

Usage (from Backend directory):
  python scripts/remove_major_id_from_profiles.py
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

    # Filter all docs that have student_profile.major_id
    filter_q = {"student_profile.major_id": {"$exists": True}}
    unset_q = {"$unset": {"student_profile.major_id": ""}}
    result = await users_col.update_many(filter_q, unset_q, bypass_document_validation=True)
    print(f"Matched: {result.matched_count}, Modified: {result.modified_count}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
