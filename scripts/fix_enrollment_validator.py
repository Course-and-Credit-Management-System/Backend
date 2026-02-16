import asyncio
import os
import sys

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    settings = Settings()
    print(f"Connecting to DB: {settings.MONGODB_DB_NAME}")
    
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    # Target "Enrollments"
    collections_cursor = await db.list_collections()
    collections_info = await collections_cursor.to_list(length=None)
    
    col_name = "Enrollments"
    col_info = next((c for c in collections_info if c["name"] == col_name), None)
    
    if not col_info:
        print(f"{col_name} collection not found. Checking 'enrollments'...")
        col_name = "enrollments"
        col_info = next((c for c in collections_info if c["name"] == col_name), None)
    
    if not col_info:
        print(f"Collection {col_name} not found.")
        return

    print(f"Targeting collection: {col_name}")
    options = col_info.get("options", {})
    validator = options.get("validator", {})
    
    if not validator:
        print("No validator found on collection.")
        return

    import json
    # print("Current Validator:", json.dumps(validator, default=str))

    # Helper to append 'null' to bsonType
    def add_null_type(type_def):
        if not type_def: return type_def
        
        # If it's a string, make it list ["string", "null"]
        if isinstance(type_def, str):
            if type_def != "null":
                return [type_def, "null"]
            return type_def
            
        # If it's already a list, check if "null" is there
        if isinstance(type_def, list):
            if "null" not in type_def:
                type_def.append("null")
            return type_def
        return type_def

    # Recursive finder
    def patch_schema(schema):
        modified = False
        if isinstance(schema, dict):
            # Check if this node is defining properties for 'grade', 'points', etc.
            if "properties" in schema:
                props = schema["properties"]
                
                # Patch 'grade'
                if "grade" in props:
                    print("Found 'grade'...")
                    grade_rules = props["grade"]
                    
                    # 1. Fix bsonType
                    if "bsonType" in grade_rules:
                        old = grade_rules["bsonType"]
                        new = add_null_type(old)
                        if old != new:
                            grade_rules["bsonType"] = new
                            print(f"Updated grade.bsonType: {old} -> {new}")
                            modified = True
                    
                    # 2. Fix enum - MUST include null if we allow null
                    if "enum" in grade_rules and isinstance(grade_rules["enum"], list):
                        if None not in grade_rules["enum"]:
                            grade_rules["enum"].append(None)
                            print("Updated grade.enum: Added null")
                            modified = True
                            
                # Patch 'points'
                if "points" in props:
                    print("Found 'points'...")
                    pts_rules = props["points"]
                    if "bsonType" in pts_rules:
                        old = pts_rules["bsonType"]
                        new = add_null_type(old)
                        if old != new:
                            pts_rules["bsonType"] = new
                            print(f"Updated points.bsonType: {old} -> {new}")
                            modified = True

                # Patch 'scores'
                if "scores" in props:
                    print("Found 'scores'...")
                    sc_rules = props["scores"]
                    if "bsonType" in sc_rules:
                        old = sc_rules["bsonType"]
                        new = add_null_type(old)
                        if old != new:
                            sc_rules["bsonType"] = new
                            print(f"Updated scores.bsonType: {old} -> {new}")
                            modified = True

            # Add 'reason' to properties if missing (optional string)
            if "properties" in schema and "reason" not in schema["properties"]:
                 print("Adding 'reason' field to validator properties...")
                 schema["properties"]["reason"] = {
                     "bsonType": ["string", "null"],
                     "description": "Reason for status change"
                 }
                 modified = True

            # Recurse values
            for k, v in schema.items():
                if patch_schema(v):
                    modified = True
                    
        elif isinstance(schema, list):
            for item in schema:
                if patch_schema(item):
                    modified = True
        return modified

    if patch_schema(validator):
        print("Validator modified in memory. Applying...")
        try:
           cmd = {"collMod": col_name, "validator": validator}
           await db.command(cmd)
           print("Successfully updated MongoDB Validator!")
        except Exception as e:
            print(f"Failed to update validator: {e}")
    else:
        print("No changes needed or fields not found in validator.")

if __name__ == "__main__":
    asyncio.run(main())
