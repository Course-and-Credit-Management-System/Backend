import requests
import json

# First get a list of students to find a valid student_id
response = requests.get('http://localhost:8001/api/v1/admin/students', headers={'Cookie': 'session=test'})
if response.status_code == 200:
    students = response.json()
    if students and len(students) > 0:
        student = students[0]
        print(f'Found student: {student["user_id"]} - {student["name"]}')
        
        # Now try to update this student
        update_response = requests.post(
            f'http://localhost:8001/api/v1/admin/students/{student["user_id"]}/update',
            json={'major': 'SE'},
            headers={'Content-Type': 'application/json', 'Cookie': 'session=test'}
        )
        
        print(f'Update Status: {update_response.status_code}')
        print(f'Update Response: {update_response.text}')
else:
    print('Failed to get students')
