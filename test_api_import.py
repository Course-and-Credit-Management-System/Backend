import asyncio
import sys
import os
import requests

async def test_api_import():
    print("Testing API import...")
    
    # Path to Excel file
    excel_path = r"C:\Users\User\Desktop\Course Enroll\sample_exam_results_import.xlsx"
    
    try:
        # Prepare multipart form data
        with open(excel_path, 'rb') as f:
            files = {'file': (excel_path, f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
            
            # Make the request
            response = requests.post(
                'http://localhost:8001/api/v1/admin/exam-results/import-excel',
                files=files
            )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"✅ Import successful!")
                print(f"📊 Inserted: {result.get('inserted', 0)} records")
                print(f"📊 Updated: {result.get('updated', 0)} records")
                if result.get('errors'):
                    print(f"⚠️  Errors: {len(result['errors'])}")
                    for error in result['errors'][:3]:  # Show first 3 errors
                        print(f"   Row {error['row']}: {error['error']}")
            else:
                print(f"❌ Import failed: {result.get('message', 'Unknown error')}")
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_api_import())
