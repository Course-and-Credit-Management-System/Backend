import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def fix_exam_validator():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    collections_cursor = await db.list_collections()
    collections_info = await collections_cursor.to_list(length=None)
    exam_col_info = next((c for c in collections_info if c['name'] in ['ExamResults', 'exam_results']), None)
    
    if not exam_col_info:
        print('ExamResults collection not found')
        return
        
    col_name = exam_col_info["name"]
    print(f'Updating validator for collection: {col_name}')
    
    options = exam_col_info.get('options', {})
    validator = options.get('validator', {})
    
    if not validator:
        print('No validator found to update')
        return

    # Update the validator to include missing status and grade values
    if '$jsonSchema' in validator and 'properties' in validator['$jsonSchema']:
        # Update status enum to include "Probation"
        if 'status' in validator['$jsonSchema']['properties']:
            current_status_enum = validator['$jsonSchema']['properties']['status'].get('enum', [])
            if 'Probation' not in current_status_enum:
                validator['$jsonSchema']['properties']['status']['enum'] = ['Passed', 'Failed', 'Probation', 'Withdrawn']
                print('Updated status enum to include "Probation"')
        
        # Update grade enum to include "C-"
        if 'grade' in validator['$jsonSchema']['properties']:
            current_grade_enum = validator['$jsonSchema']['properties']['grade'].get('enum', [])
            if 'C-' not in current_grade_enum:
                validator['$jsonSchema']['properties']['grade']['enum'] = [
                    "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F"
                ]
                print('Updated grade enum to include "C-"')
    
    # Apply the updated validator
    try:
        cmd = {"collMod": col_name, "validator": validator}
        await db.command(cmd)
        print('Successfully updated MongoDB Validator for ExamResults!')
    except Exception as e:
        print(f'Failed to update validator: {e}')

if __name__ == "__main__":
    asyncio.run(fix_exam_validator())
