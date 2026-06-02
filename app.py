from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import os
import base64
import cv2
import numpy as np
from datetime import datetime
import json

import database as db
from qr_manager import QRManager
from face_engine import FaceEngine

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize components
qr_manager = QRManager()
face_engine = FaceEngine()

# In-memory store for active QR sessions
active_qr_sessions = {}

# ============ Professor Routes ============
@app.route('/')
def index():
    return render_template('professor_dashboard.html')

@app.route('/professor/login', methods=['POST'])
def professor_login():
    data = request.json
    employee_id = data.get('employee_id')
    password = data.get('password')
    
    # Verify professor (simplified - implement proper auth)
    professor = db.get_professor_by_employee_id(employee_id)
    if professor:
        return jsonify({'success': True, 'professor': professor})
    return jsonify({'success': False, 'error': 'Invalid credentials'})

@app.route('/api/generate-qr', methods=['POST'])
def generate_qr():
    """Professor generates QR code for current lecture"""
    data = request.json
    lecture_id = data.get('lecture_id')
    professor_id = data.get('professor_id')
    
    # Create QR session in database
    session_id, qr_token = db.create_qr_session(lecture_id, professor_id, valid_minutes=2)
    
    # Generate QR image
    qr_path, qr_url = qr_manager.generate_qr(qr_token, lecture_id)
    
    # Store in active sessions
    active_qr_sessions[qr_token] = {
        'lecture_id': lecture_id,
        'professor_id': professor_id,
        'expires_at': datetime.now().timestamp() + 120,
        'used_by': []
    }
    
    return jsonify({
        'success': True,
        'qr_token': qr_token,
        'qr_url': qr_url,
        'qr_image': f'/qr-image/{qr_token}',
        'expires_in': 120
    })

@app.route('/qr-image/<qr_token>')
def serve_qr_image(qr_token):
    """Serve QR code image"""
    qr_path = os.path.join('qr_codes', f'{qr_token}.png')
    if os.path.exists(qr_path):
        return send_file(qr_path, mimetype='image/png')
    return jsonify({'error': 'QR not found'}), 404

# ============ Student Routes ============
@app.route('/attendance')
def attendance_form():
    """Student attendance page (scanned from QR)"""
    qr_token = request.args.get('qr')
    if not qr_token:
        return "Invalid QR Code", 400
    
    # Verify QR token is valid
    qr_info, message = db.verify_qr_token(qr_token)
    if not qr_info:
        return f"QR Code Error: {message}", 400
    
    return render_template('attendance_form.html', qr_token=qr_token)

@app.route('/api/submit-attendance', methods=['POST'])
def submit_attendance():
    """Student submits attendance with photo and location"""
    data = request.json
    
    roll_no = data.get('rollNo')
    student_name = data.get('studentName')
    photo_base64 = data.get('photo')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    qr_token = data.get('qrToken')
    ip_address = request.remote_addr
    
    # 1. Get student from database
    student = db.get_student_by_roll(roll_no)
    if not student:
        return jsonify({'success': False, 'error': 'Student not found'})
    
    # Verify name matches
    if student['name'].lower() != student_name.lower():
        return jsonify({'success': False, 'error': 'Name does not match records'})
    
    # 2. Verify QR token
    qr_info, message = db.verify_qr_token(qr_token)
    if not qr_info:
        return jsonify({'success': False, 'error': message})
    
    lecture_id = qr_info['lecture_id']
    qr_session_id = qr_info['id']
    
    # 3. Verify face in photo
    face_verified, face_confidence = verify_face_photo(photo_base64, student['id'])
    
    # 4. Verify location (check if within college campus)
    location_verified, location_msg = verify_location(latitude, longitude)
    
    # 5. Determine status
    if face_verified and location_verified:
        status = "Present"
        remarks = "Full verification passed"
    elif face_verified and not location_verified:
        status = "Present - Location Mismatch"
        remarks = f"Face OK, but {location_msg}"
    elif not face_verified and location_verified:
        status = "Present - Face Mismatch"
        remarks = "Location OK, but face verification failed"
    else:
        status = "Failed Verification"
        remarks = "Both face and location verification failed"
    
    # Save photo to disk
    photo_path = save_attendance_photo(photo_base64, student['id'], lecture_id)
    
    # 6. Mark attendance
    verification_data = {
        'face_verified': face_verified,
        'face_confidence': face_confidence,
        'location_verified': location_verified,
        'latitude': latitude,
        'longitude': longitude,
        'status': status,
        'remarks': remarks,
        'device_info': request.headers.get('User-Agent'),
        'ip_address': ip_address,
        'photo_path': photo_path
    }
    
    success, msg = db.mark_attendance(lecture_id, student['id'], qr_session_id, verification_data)
    
    if success:
        # Mark QR as used by this student
        db.mark_qr_used(qr_session_id, student['id'])
        
        # Emit real-time update to professor's dashboard
        socketio.emit('attendance_update', {
            'student_name': student['name'],
            'roll_no': roll_no,
            'status': status,
            'timestamp': datetime.now().isoformat()
        })
        
        return jsonify({
            'success': True,
            'message': 'Attendance marked successfully',
            'face_verified': face_verified,
            'location_verified': location_verified,
            'status': status
        })
    
    return jsonify({'success': False, 'error': msg})

def verify_face_photo(photo_base64, student_id):
    """Decode base64 photo and compare with stored face"""
    try:
        # Remove data URL prefix if present
        if ',' in photo_base64:
            photo_base64 = photo_base64.split(',')[1]
        
        # Decode base64 to image
        img_bytes = base64.b64decode(photo_base64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return False, 0
        
        # Recognize face
        recognized_id, confidence, _ = face_engine.recognize_frame(img)
        
        if recognized_id == student_id and confidence < 80:
            return True, confidence
        return False, confidence
    except Exception as e:
        print(f"Face verification error: {e}")
        return False, 0

def verify_location(latitude, longitude):
    """Verify if location is within college campus"""
    # Define campus boundaries (update with your college's coordinates)
    CAMPUS_BOUNDS = {
        'lat_min': 19.130, 'lat_max': 19.140,
        'lon_min': 72.910, 'lon_max': 72.930
    }
    
    if CAMPUS_BOUNDS['lat_min'] <= latitude <= CAMPUS_BOUNDS['lat_max'] and \
       CAMPUS_BOUNDS['lon_min'] <= longitude <= CAMPUS_BOUNDS['lon_max']:
        return True, "Within campus"
    return False, "Outside campus boundary"

def save_attendance_photo(photo_base64, student_id, lecture_id):
    """Save the submitted photo for audit"""
    try:
        if ',' in photo_base64:
            photo_base64 = photo_base64.split(',')[1]
        
        img_bytes = base64.b64decode(photo_base64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Create directory
        save_dir = f"attendance_images/lecture_{lecture_id}"
        os.makedirs(save_dir, exist_ok=True)
        
        # Save with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"student_{student_id}_{timestamp}.jpg"
        filepath = os.path.join(save_dir, filename)
        
        cv2.imwrite(filepath, img)
        return filepath
    except Exception as e:
        print(f"Error saving photo: {e}")
        return None

# ============ Professor Dashboard Routes ============
@app.route('/api/lecture/attendance/<int:lecture_id>')
def get_lecture_attendance(lecture_id):
    """Get attendance records for a lecture"""
    records = db.get_lecture_attendance(lecture_id)
    bunkers = db.detect_bunkers(lecture_id)
    
    return jsonify({
        'attendance': records,
        'bunkers': bunkers,
        'total_present': len(records),
        'total_bunkers': len(bunkers)
    })

@app.route('/api/student/report/<int:student_id>')
def student_report(student_id):
    """Get student's attendance report"""
    report = db.get_student_attendance_percentage(student_id)
    return jsonify(report)

# ============ Real-time WebSocket Events ============
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('professor_join')
def handle_professor_join(data):
    lecture_id = data.get('lecture_id')
    emit('joined', {'lecture_id': lecture_id}, broadcast=True)

if __name__ == '__main__':
    # Initialize database
    db.init_db()
    
    # Create templates directory if not exists
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    print("=" * 50)
    print("🚀 Attendance System Server Starting...")
    print("📍 URL: http://localhost:5000")
    print("=" * 50)
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
