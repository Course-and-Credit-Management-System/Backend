import asyncio
import os
import sys

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

def transform_value(val):
    if not val or not isinstance(val, str):
        return val, False
    
    val_str = val.strip()
    original_val = val_str
    
    # CASE 1: Contains "(new)"
    if "(new)" in val_str:
        clean = val_str.replace("(new)", "").strip()
        clean = clean.replace(",", " .")
        val_str = f"New . {clean}"
        
    # CASE 2: startswith "new."
    elif val_str.lower().startswith("new."):
        clean = val_str[4:].strip() 
        clean = clean.replace(",", " .")
        val_str = f"New . {clean}"

    # CASE 3: Contains "(old)"
    elif "(old)" in val_str:
        clean = val_str.replace("(old)", "").strip()
        clean = clean.replace(",", " .")
        val_str = f"Old . {clean}"

    # CASE 4: Matches "Old • "
    elif "Old • " in val_str:
        val_str = val_str.replace("•", ".")

    # Cleanup spacing
    val_str = val_str.replace(" .", ".").replace(".", " . ")
    val_str = " ".join(val_str.split())
    
    return val_str, (val_str != original_val)

async def main():
    settings = Settings()
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    cols = await db.list_collection_names()
    print(f"Collections found: {cols}")
    
    # Try finding the users collection
    user_col_name = None
    for name in ["Users", "User", "users", "user"]:
        if name in cols:
            user_col_name = name
            break
            
    if not user_col_name:
        print("Could not find Users collection!")
        # Fallback to creating one or just exiting?
        # If it's not in the list, maybe it's strictly case sensitive and I missed it?
        # Let's try iterating all collections if needed, but 'Users' is likely.
        return

    print(f"Targeting collection: {user_col_name}")
    col = db[user_col_name]
    
    # Fetch all students
    cursor = col.find({})
    
    updated_count = 0
    checked_count = 0
    
    async for doc in cursor:
        checked_count += 1
        # Check 1: student_profile.current_year
        profile = doc.get("student_profile")
        if isinstance(profile, dict):
            cy = profile.get("current_year")
            if cy:
                new_cy, changed = transform_value(cy)
                if changed:
                    print(f"User {doc.get('user_id', doc.get('_id'))} (profile): '{cy}' -> '{new_cy}'")
                    await col.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"student_profile.current_year": new_cy}}
                    )
                    updated_count += 1
        
        # Check 2: Top level current_year (just in case schema versioning mix)
        top_cy = doc.get("current_year")
        if top_cy:
            new_top_cy, changed = transform_value(top_cy)
            if changed:
                print(f"User {doc.get('user_id', doc.get('_id'))} (root): '{top_cy}' -> '{new_top_cy}'")
                await col.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"current_year": new_top_cy}}
                )
                updated_count += 1

    print(f"Checked {checked_count} documents. Updated {updated_count}.")

if __name__ == "__main__":
    asyncio.run(main())
