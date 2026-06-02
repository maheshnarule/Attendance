"""Test script for attendance system"""

import requests
import base64
import json

BASE_URL = "http://localhost:5000"

def test_qr_generation():
    """Test QR code generation"""
    response = requests.post(f"{BASE_URL}/api/generate-qr", json={
        "lecture_id": 1,
        "professor_id": 1
    })
    print(f"QR Generation: {response.json()}")
    return response.json().get('qr_token')

def test_attendance_submission(qr_token):
    """Test attendance submission with mock data"""
    
    # Create a dummy image (black image as placeholder)
    dummy_image = "data:image/jpeg;base64," + base64.b64encode(b'\x00' * 1000).decode()
    
    data = {
        "rollNo": "CS001",
        "studentName": "John Doe",
        "photo": dummy_image,
        "latitude": 19.135,
        "longitude": 72.920,
        "qrToken": qr_token
    }
    
    response = requests.post(f"{BASE_URL}/api/submit-attendance", json=data)
    print(f"Attendance Submission: {response.json()}")

def test_report():
    """Test fetching attendance report"""
    response = requests.get(f"{BASE_URL}/api/lecture/attendance/1")
    print(f"Report: {response.json()}")

if __name__ == "__main__":
    print("Running tests...")
    
    # Uncomment to test each endpoint
    # token = test_qr_generation()
    # if token:
    #     test_attendance_submission(token)
    # test_report()
    
    print("Tests completed!")