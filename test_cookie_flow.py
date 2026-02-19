import requests
import json

def test_cookie_flow():
    print("=== Testing Cookie Flow ===")
    
    # Step 1: Login to get a valid token
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
    
    if login_response.status_code == 200:
        login_result = login_response.json()
        token = login_result.get('access_token')
        print(f"✅ Got token: {token[:20]}...")
        
        # Step 2: Use the token to access a protected endpoint
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        
        # Test with Authorization header
        auth_response = requests.get(
            'http://localhost:8001/api/v1/admin/students',
            headers=headers
        )
        
        print(f"Auth Header Test Status: {auth_response.status_code}")
        
        if auth_response.status_code == 200:
            print("✅ Authorization header works!")
            students = auth_response.json()
            if students and len(students) > 0:
                print(f"Found {len(students)} students")
        else:
            print("❌ No students found")
    else:
        print(f"❌ Login failed: {login_response.text}")
    
    print("\n=== Testing Cookie Flow ===")
    
    # Step 3: Login again to test cookie setting
    login_response2 = requests.post(
        'http://localhost:8001/api/v1/auth/login',
        json=login_data,
        headers={'Content-Type': 'application/json'}
    )
    
    print(f"Second Login Status: {login_response2.status_code}")
    
    if login_response2.status_code == 200:
        login_result2 = login_response2.json()
        token2 = login_result2.get('access_token')
        print(f"✅ Got token2: {token2[:20]}...")
        
        # Test with cookie (should be set by frontend)
        cookie_response = requests.get(
            'http://localhost:8001/api/v1/admin/students',
            headers={'Cookie': f'access_token={token2}'}
        )
        
        print(f"Cookie Test Status: {cookie_response.status_code}")
        
        if cookie_response.status_code == 200:
            print("✅ Cookie auth works!")
            students = cookie_response.json()
            if students and len(students) > 0:
                print(f"Found {len(students)} students")
        else:
            print("❌ Cookie test failed")
    else:
        print(f"❌ Second login failed: {login_response2.text}")

if __name__ == "__main__":
    test_cookie_flow()
