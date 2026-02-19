import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient

async def test_student_update():
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB_NAME]
    
    # Test updating a student's major
    student_id = "TNT-8801"  # Use existing student
    update_data = {
        "major": "SE"  # Change from CS to SE
    }
    
    print(f'Testing update for student {student_id}: {update_data}')
    
    try:
        import requests
        response = requests.post(
            f'http://localhost:8001/api/v1/admin/students/{student_id}/update',
            json=update_data,
            headers={'Content-Type': 'application/json'}
        )
        
        print(f'Status Code: {response.status_code}')
        print(f'Response: {response.text}')
        
        if response.status_code == 200:
            result = response.json()
            print(f'✅ Update successful: {result}')
        else:
            print(f'❌ Update failed: {response.text}')
            
    except Exception as e:
        print(f'❌ Error: {e}')

if __name__ == "__main__":
    asyncio.run(test_student_update())
