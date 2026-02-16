import asyncio
import os
import sys

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient
from app.models.enums import AcademicYear

async def main():
    settings = Settings()
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    # Get all valid tensor values from the updated Enum
    valid_years = [e.value for e in AcademicYear]
    print(f"Found {len(valid_years)} valid AcademicYear values.")
    
    # We need to update the validator for the 'Users' collection.
    # The validator is likely on 'student_profile.current_year'.
    
    # Use collMod command to update validator
    # We strictly only want to update the enum list for this specific field, 
    # but constructing the full validator correctly is hard without overwriting other rules.
    # Ideally, we fetch the current validator, modify it, then set it back.
    
    # 1. Get current info
    # In newer Motor/PyMongo, list_collections is async and returns a cursor
    collections_cursor = await db.list_collections()
    collections_info = await collections_cursor.to_list(length=None)
    user_col_info = next((c for c in collections_info if c["name"] == "Users"), None)
    
    if not user_col_info:
        # try 'users' or 'User'
        user_col_info = next((c for c in collections_info if c["name"] in ["users", "User"]), None)
        
    if not user_col_info:
        print("Users collection not found.")
        return
        
    col_name = user_col_info["name"]
    print(f"Targeting collection: {col_name}")
    
    options = user_col_info.get("options", {})
    validator = options.get("validator", {})
    
    import json
    # print("Current Validator:", json.dumps(validator, default=str))
    
    if not validator:
        print("No validator found on collection.")
        return

    # Deep dive into validator structure to find 'current_year' enum
    # Structure: $jsonSchema -> oneOf -> [ ... properties -> student_profile -> properties -> current_year -> enum ... ]
    
    def update_enum_recursive(schema):
        found = False
        if isinstance(schema, dict):
            for k, v in schema.items():
                if k == "current_year" and isinstance(v, dict) and "enum" in v:
                    print("Found current_year enum! Updating...")
                    v["enum"] = valid_years
                    found = True
                else:
                    if update_enum_recursive(v):
                        found = True
        elif isinstance(schema, list):
            for item in schema:
                if update_enum_recursive(item):
                    found = True
        return found

    if update_enum_recursive(validator):
        print("Validator modified in memory.")
        # Apply change
        try:
           # command: { collMod: <collection>, validator: <validator>, validationLevel: <level>, ... }
           cmd = {"collMod": col_name, "validator": validator}
           await db.command(cmd)
           print("Successfully updated MongoDB Validator!")
        except Exception as e:
            print(f"Failed to update validator: {e}")
    else:
        print("Could not locate 'current_year' enum definition in the validator schema.")

if __name__ == "__main__":
    asyncio.run(main())
