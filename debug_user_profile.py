import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient

async def debug_user():
    # Try default Mongo URI
    uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    print(f"Connecting to {uri}...")
    
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=2000)
    db = client["school_db"]
    
    try:
        user = await db.users.find_one({"user_id": "TNT-8808"})
        if user:
            print("--- User Found ---")
            print(f"ID: {user.get('user_id')}")
            profile = user.get("student_profile", {})
            print(f"Student Profile: {profile}")
            cy = profile.get('current_year')
            print(f"Current Year (Raw): '{cy}'")
            print("------------------")
        else:
            print("User TNT-8808 not found.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(debug_user())
