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
    settings = Settings()
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[Course]
    )
    
    print("Fetching courses...")
    courses = await Course.find_all().to_list()
    
    updated_count = 0
    
    for c in courses:
        modified = False
        if not c.semester:
            continue
            
        new_sem_list = []
        for item in c.semester:
            # item is expected to be a dict based on model, but we should be safe
            if isinstance(item, dict):
                val = item.get("semester", "")
                modified_val = val
                
                # Rule 1 from "new." prefix (current state)
                if val and str(val).startswith("new."):
                    # "new.1st Year, First Sem" -> "New . 1st Year . First Sem"
                    # Replace "new." with "New . " and ", " with " . "
                    modified_val = val.replace("new.", "New . ").replace(", ", " . ")

                # Rule 2 from "(new)" suffix (original state)
                elif val and str(val).strip().endswith("(new)"):
                    # "1st Year, First Sem(new)" -> "New . 1st Year . First Sem"
                    clean_val = val.replace("(new)", "").strip()
                    modified_val = f"New . {clean_val}".replace(", ", " . ")
                    
                if modified_val != val:
                    item["semester"] = modified_val
                    modified = True
                    print(f"Updating '{c.course_code}': '{val}' -> '{modified_val}'")
                    
            elif isinstance(item, str):
                 # Handle legacy plain strings if any
                 if item.strip().endswith("(new)"):
                    clean_val = item.replace("(new)", "").strip()
                    new_val = f"New . {clean_val}"
                    # Wrap in dict to match schema? Or keep as string if Mixed allowed?
                    # The schema is List[Dict] or List[SemesterItem], so likely dicts.
                    # But Python list can hold anything.
                    # I'll convert to dict to be safe with Schema if I'm touching it.
                    # Wait, if it was string, Beanie might complain on save if Schema is strict.
                    # The schema in `course.py` says `semester: List[Dict[str, Any]]`.
                    # So strings shouldn't exist.
                    pass
            
            new_sem_list.append(item)
            
        if modified:
            await c.update({"$set": {"semester": new_sem_list}})
            updated_count += 1

    print(f"\nMigration complete. Updated {updated_count} courses.")

if __name__ == "__main__":
    asyncio.run(main())
