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
    
    val = val.strip()
    original_val = val
    
    # CASE 1: Contains "(new)"
    if "(new)" in val:
        # Remove (new)
        clean = val.replace("(new)", "").strip()
        # Format: "New . {Value}"
        # We also need to replace comma with " . "
        clean = clean.replace(",", " .")
        # Ensure single spaces around dots
        # "1st Year . First Sem"
        
        val = f"New . {clean}"
        
    # CASE 2: startswith "new." (from previous migration)
    elif val.lower().startswith("new."):
        clean = val[4:].strip() # Remove "new."
        clean = clean.replace(",", " .")
        val = f"New . {clean}"

    # CASE 3: Contains "(old)"
    elif "(old)" in val:
        clean = val.replace("(old)", "").strip()
        clean = clean.replace(",", " .")
        val = f"Old . {clean}"

    # CASE 4: Matches "Old • " format (Standardizing)
    elif "Old • " in val:
        # replace bullet with dot
        val = val.replace("•", ".")
        # Ensure "Old . "
        # It might already be "Old . " if bullet replaced
        # "Old . 4th Year . First Sem"
        pass
        
    # Standardize spacing around dots? 
    # User wanted "New . 1st Year . First Sem"
    # Logic: Replace " ." with " ." (noop) or "," with " ."
    
    # Final cleanup to ensure " . " spacing
    # This might be tricky if we have "New.1st" vs "New . 1st"
    # Basic normalization:
    val = val.replace(" .", ".").replace(".", " . ") 
    # Now we have "Key .  Value" (double spaces?)
    val = " ".join(val.split()) 
    # Now "Key . Value"
    
    return val, (val != original_val)

async def main():
    settings = Settings()
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    # ---------------------------
    # 1. Update COURSES
    # ---------------------------
    print("Migrating Courses...")
    courses_coll = db["Courses"]
    courses = await courses_coll.find({}).to_list(length=None)
    
    c_count = 0
    for c in courses:
        modified = False
        sem_list = c.get("semester", [])
        if not sem_list: continue
        
        new_list = []
        for item in sem_list:
            if isinstance(item, dict):
                v_str = item.get("semester", "")
                new_v, changed = transform_value(v_str)
                if changed:
                    item["semester"] = new_v
                    modified = True
                    print(f"Course {c.get('course_code')}: '{v_str}' -> '{new_v}'")
            new_list.append(item)
            
        if modified:
            await courses_coll.update_one({"_id": c["_id"]}, {"$set": {"semester": new_list}})
            c_count += 1
            
    print(f"Courses updated: {c_count}")

    # ---------------------------
    # 2. Update ENROLLMENTS
    # ---------------------------
    print("Migrating Enrollments...")
    enr_coll = db["Enrollment"] # Check actual collection name if Beanie defaults used
    # Beanie usually uses Class Name as collection name if not specified.
    # Enrollment class has no Settings inner class in snippet? Let's assume "Enrollment"
    # Wait, check enrollment.py model in previous reads...
    # It wasn't fully read. Beanie default is pascal case "Enrollment".
    
    # Let's check listing
    cols = await db.list_collection_names()
    enr_name = "Enrollment"
    if "Enrollments" in cols: enr_name = "Enrollments"
    if "enrollment" in cols: enr_name = "enrollment"
    
    print(f"Using Enrollment Collection: {enr_name}")
    enr_coll = db[enr_name]
    
    enrollments = await enr_coll.find({}).to_list(length=None)
    e_count = 0
    for e in enrollments:
        att = e.get("semester_attend") # Beanie aliases might map semesterAttend -> semester_attend in python, but in DB?
        # Check raw doc keys
        # If model says `semesterAttend` aliased or not?
        # Usually snake_case in python, camelCase in DB if aliases used. Alternatively snake_case in DB
        # I'll check the keys present
        
        target_key = "semester_attend"
        if "semesterAttend" in e: target_key = "semesterAttend"
        elif "semester_attend" in e: target_key = "semester_attend"
        
        val = e.get(target_key)
        new_val, changed = transform_value(val)
        
        if changed:
            await enr_coll.update_one({"_id": e["_id"]}, {"$set": {target_key: new_val}})
            e_count += 1
            print(f"Enrollment {e.get('_id')}: '{val}' -> '{new_val}'")

    print(f"Enrollments updated: {e_count}")

    # ---------------------------
    # 3. Update USERS
    # ---------------------------
    print("Migrating Users...")
    users_coll = db["Users"] # Check name
    if "User" in cols: users_coll = db["User"]
    if "users" in cols: users_coll = db["users"]
    
    users = await users_coll.find({"role": "student"}).to_list(length=None)
    u_count = 0
    for u in users:
        profile = u.get("student_profile")
        if not profile: continue
        
        # Check key in profile
        p_key = "current_year"
        val = profile.get(p_key)
        
        new_val, changed = transform_value(val)
        
        if changed:
            # Update embedded field
            await users_coll.update_one(
                {"_id": u["_id"]}, 
                {"$set": {f"student_profile.{p_key}": new_val}}
            )
            u_count += 1
            print(f"User {u.get('user_id')}: '{val}' -> '{new_val}'")

    print(f"Users updated: {u_count}")

if __name__ == "__main__":
    asyncio.run(main())
