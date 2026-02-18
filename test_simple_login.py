import requests
import json

def test_simple_login():
    print("=== Testing Simple Login ===")
    
    # Test login with username "admin" and password "mtt"
    login_data = {
        "username": "admin",
        "password": "mtt",
        "role": "admin"
    }
    
    login_response = requests.post(
        'http://localhost:8001/api/v1/auth/login',
        json=login_data,
        headers={'Content-Type': 'application/json'}
    )
    
    print(f"Login Status: {login_response.status_code}")
    print(f"Login Response: {login_response.text}")
    
    if login_response.status_code == 200:
        login_result = login_response.json()
        token = login_result.get('access_token')
        print(f"✅ Got token: {token[:20]}...")
        
        # Test student update with the token
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        
        # Find a student to update
        students_response = requests.get(
            'http://localhost:8001/api/v1/admin/students',
            headers=headers
        )
        
        if students_response.status_code == 200:
            students = students_response.json()
            if students and len(students) > 0:
                student = students[0]
                student_id = student.get('user_id')
                print(f"✅ Found student: {student_id} - {student.get('name')}")
                
                # Update student major to SE
                update_data = {'major': 'SE'}
                update_response = requests.post(
                    f'http://localhost:8001/api/v1/admin/students/{student_id}/update',
                    json=update_data,
                    headers=headers
                )
                
                print(f"Update Status: {update_response.status_code}")
                print(f"Update Response: {update_response.text}")
                
                if update_response.status_code == 200:
                    print("✅ Student update successful!")
                else:
                    print(f"❌ Student update failed: {update_response.text}")
            else:
                print("❌ No students found")
    else:
        print(f"❌ Login failed: {login_response.text}")

if __name__ == "__main__":
    test_simple_login()
