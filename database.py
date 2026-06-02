import sqlite3
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = "attendance.db"

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Initialize database with schema"""
    with open('database_schema.sql', 'r') as f:
        schema = f.read()
    
    with get_db() as conn:
        conn.executescript(schema)
    print("✅ Database initialized")

# ============ Student Operations ============
def get_student_by_roll(roll_no):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM students WHERE roll_no = ?", (roll_no,)
        ).fetchone()
        return dict(row) if row else None

def get_student_by_id(student_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()
        return dict(row) if row else None

def get_enrolled_students(lecture_id):
    """Get all students enrolled in this lecture's subject"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT s.* FROM students s
            JOIN student_subjects ss ON s.id = ss.student_id
            JOIN lectures l ON ss.subject_id = l.subject_id
            WHERE l.id = ?
        """, (lecture_id,)).fetchall()
        return [dict(row) for row in rows]

# ============ QR Session Operations ============
def create_qr_session(lecture_id, professor_id, valid_minutes=2):
    import hashlib
    import time
    
    # Generate unique token
    token_seed = f"{lecture_id}_{professor_id}_{time.time()}"
    qr_token = hashlib.sha256(token_seed.encode()).hexdigest()[:32]
    
    expires_at = datetime.now() + timedelta(minutes=valid_minutes)
    
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO qr_sessions (lecture_id, qr_token, expires_at, professor_id)
            VALUES (?, ?, ?, ?)
        """, (lecture_id, qr_token, expires_at.isoformat(), professor_id))
        
        return cursor.lastrowid, qr_token

def verify_qr_token(qr_token):
    """Check if QR token is valid and not expired"""
    with get_db() as conn:
        row = conn.execute("""
            SELECT * FROM qr_sessions 
            WHERE qr_token = ? AND is_active = 1
        """, (qr_token,)).fetchone()
        
        if not row:
            return None, "Invalid QR code"
        
        expires_at = datetime.fromisoformat(row['expires_at'])
        if datetime.now() > expires_at:
            # Deactivate expired QR
            conn.execute(
                "UPDATE qr_sessions SET is_active = 0 WHERE id = ?",
                (row['id'],)
            )
            return None, "QR code expired (2 minute window)"
        
        return dict(row), "Valid"

def mark_qr_used(qr_session_id, student_id):
    with get_db() as conn:
        conn.execute("""
            UPDATE qr_sessions 
            SET used_count = used_count + 1 
            WHERE id = ?
        """, (qr_session_id,))

# ============ Attendance Operations ============
def mark_attendance(lecture_id, student_id, qr_session_id, verification_data):
    """Mark attendance with all verification checks"""
    
    with get_db() as conn:
        # Check if already marked
        existing = conn.execute("""
            SELECT id FROM attendance 
            WHERE lecture_id = ? AND student_id = ?
        """, (lecture_id, student_id)).fetchone()
        
        if existing:
            return False, "Attendance already marked"
        
        # Insert attendance record
        conn.execute("""
            INSERT INTO attendance (
                lecture_id, student_id, qr_session_id,
                face_verified, face_confidence, 
                location_verified, latitude, longitude,
                status, remarks, device_info, ip_address, photo_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lecture_id, student_id, qr_session_id,
            verification_data['face_verified'],
            verification_data['face_confidence'],
            verification_data['location_verified'],
            verification_data.get('latitude'),
            verification_data.get('longitude'),
            verification_data['status'],
            verification_data['remarks'],
            verification_data.get('device_info'),
            verification_data.get('ip_address'),
            verification_data.get('photo_path')
        ))
        
        return True, "Attendance marked successfully"

def get_lecture_attendance(lecture_id):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT a.student_id, s.name, s.roll_no, a.status, a.mark_time,
                   a.face_verified, a.location_verified,
                   a.remarks
            FROM attendance a
            JOIN students s ON a.student_id = s.id
            WHERE a.lecture_id = ?
            ORDER BY a.mark_time
        """, (lecture_id,)).fetchall()
        return [dict(row) for row in rows]

# ============ Bunk Detection ============
def detect_bunkers(lecture_id):
    """Identify students who bunked the lecture"""
    enrolled = get_enrolled_students(lecture_id)
    marked = get_lecture_attendance(lecture_id)
    
    marked_student_ids = [m['student_id'] for m in marked] if marked else []
    
    bunkers = []
    for student in enrolled:
        if student['id'] not in marked_student_ids:
            bunkers.append(student)
            
            # Record in bunk table if not already recorded
            with get_db() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO bunk_records (student_id, lecture_id, reason)
                    VALUES (?, ?, ?)
                """, (student['id'], lecture_id, 'QR not scanned'))
    
    return bunkers

# ============ Statistics ============
def get_student_attendance_percentage(student_id, semester=None):
    with get_db() as conn:
        query = """
            SELECT 
                COUNT(*) as total_lectures,
                SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) as present_count
            FROM attendance a
            JOIN lectures l ON a.lecture_id = l.id
            WHERE a.student_id = ?
        """
        params = [student_id]
        
        if semester:
            query += " AND l.semester = ?"
            params.append(semester)
        
        row = conn.execute(query, params).fetchone()
        
        total = row['total_lectures'] or 1
        percentage = (row['present_count'] / total) * 100 if total > 0 else 0
        
        return {
            'total': total,
            'present': row['present_count'] or 0,
            'percentage': round(percentage, 2)
        }