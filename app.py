from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import sqlite3
import hashlib
from datetime import datetime
from authlib.integrations.flask_client import OAuth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = "smart_student_planner_secret_key_123"
DB_NAME = "planner.db"

# Cấu hình Google OAuth
GOOGLE_CLIENT_ID = "679974806605-o3id9qo2ma2le35qaghelfabbpc0thmt.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.calendarlist.readonly'
    }
)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Bảng lưu thông tin tài khoản đăng ký truyền thống
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    # 2. Bảng tasks lưu user_email hoặc username để phân tách dữ liệu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            title TEXT NOT NULL,
            subject TEXT NOT NULL,
            description TEXT,
            deadline TEXT NOT NULL,
            priority TEXT NOT NULL,
            estimated_hours REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    
    # 3. Bảng lưu sự kiện lịch cho tài khoản nội bộ
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            username TEXT NOT NULL,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            location TEXT,
            description TEXT
        )
    ''')
    
    # Lưu thay đổi và đóng kết nối ở ĐÂY (sau khi đã tạo xong tất cả các bảng)
    conn.commit()
    conn.close()



# -------------------------------------------------------------
# ROUTE GIAO DIỆN CHÍNH & XÁC THỰC
# -------------------------------------------------------------
@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    return render_template('index.html', user=session.get('user'))

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hashed_password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['user'] = {
                'name': username,
                'email': username,
                'picture': 'https://www.gravatar.com/avatar/?d=mp' # Ảnh đại diện mặc định
            }
            return redirect(url_for('index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không chính xác!', 'error')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register_page():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
            conn.commit()
            conn.close()
            flash('Đăng ký thành công! Hãy đăng nhập.', 'success')
            return redirect(url_for('login_page'))
        except sqlite3.IntegrityError:
            flash('Tên đăng nhập này đã tồn tại!', 'error')
            
    return render_template('register.html')

# Google Login Routes
@app.route('/login/google')
def login_google():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    if user_info:
        session['user'] = {
            'name': user_info.get('name'),
            'email': user_info.get('email'),
            'picture': user_info.get('picture')
        }
        session['google_token'] = token  # Lưu token để gọi Google Calendar API sau này
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login_page'))

# -------------------------------------------------------------
# API QUẢN LÝ TASK (ĐÃ CÓ SẴN)
# -------------------------------------------------------------
@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    if 'user' not in session:
        return jsonify([]), 401
    
    user_email = session['user']['email']
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, subject, description, deadline, priority, estimated_hours, status, created_at 
        FROM tasks WHERE user_email = ?
    ''', (user_email,))
    rows = cursor.fetchall()
    conn.close()
    
    tasks = []
    for r in rows:
        tasks.append({
            "id": str(r[0]), "title": r[1], "subject": r[2],
            "description": r[3] or "", "deadline": r[4], "priority": r[5],
            "estimated_hours": r[6], "status": r[7], "created_at": r[8]
        })
    return jsonify(tasks)

@app.route('/api/tasks', methods=['POST'])
def add_task():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    user_email = session['user']['email']
    data = request.json
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tasks (user_email, title, subject, description, deadline, priority, estimated_hours, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_email, data.get('title'), data.get('subject'), data.get('description', ''),
          data.get('deadline'), data.get('priority'), data.get('estimated_hours'),
          data.get('status', 'To do'), datetime.now().isoformat()))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return jsonify({"success": True, "id": str(new_id)})

@app.route('/api/tasks/<int:task_id>', methods=['PUT', 'DELETE'])
def modify_task(task_id):
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_email = session['user']['email']
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if request.method == 'PUT':
        data = request.json
        if 'status' in data and len(data) == 1:
            cursor.execute('UPDATE tasks SET status = ? WHERE id = ? AND user_email = ?', (data['status'], task_id, user_email))
        else:
            cursor.execute('''
                UPDATE tasks SET title = ?, subject = ?, description = ?, deadline = ?, priority = ?, estimated_hours = ?, status = ?
                WHERE id = ? AND user_email = ?
            ''', (data.get('title'), data.get('subject'), data.get('description', ''),
                  data.get('deadline'), data.get('priority'), data.get('estimated_hours'),
                  data.get('status'), task_id, user_email))
    elif request.method == 'DELETE':
        cursor.execute('DELETE FROM tasks WHERE id = ? AND user_email = ?', (task_id, user_email))
        
    conn.commit()
    conn.close()
    return jsonify({"success": True})

#----------------------------------------------------------------------------
# API lấy sự kiện lịch (Tự động phân biệt Google Calendar hay SQLite cá nhân)
#----------------------------------------------------------------------------

@app.route('/api/calendar-events', methods=['GET'])
def get_calendar_events():
    if 'user' not in session:
        return jsonify([]), 401
    
    user_email = session['user']['email']
    
    if 'google_token' in session:
        try:
            credentials = Credentials(
                token=session['google_token']['access_token'],
                refresh_token=session['google_token'].get('refresh_token'),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET
            )
            service = build('calendar', 'v3', credentials=credentials)
            
            time_min_str = request.args.get('start')
            time_max_str = request.args.get('end')
            
            def parse_to_utc_z(date_str):
                if not date_str:
                    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                try:
                    dt = datetime.fromisoformat(date_str)
                    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                except Exception:
                    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            time_min = parse_to_utc_z(time_min_str)
            time_max = parse_to_utc_z(time_max_str) if time_max_str else None

            all_google_events = []
            
            # Tự động lấy toàn bộ danh sách lịch (My calendars + Other calendars)
            calendar_list = service.calendarList().list(minAccessRole='reader').execute()
            
            print(f"=== TỰ ĐỘNG QUÉT THẤY {len(calendar_list.get('items', []))} LỊCH ===")

            for calendar_entry in calendar_list.get('items', []):
                cal_id = calendar_entry['id']
                cal_summary = calendar_entry.get('summary', 'Không có tên')
                
                try:
                    # Tạm thời bỏ timeMin và timeMax để test xem lịch này có chứa sự kiện nào không
                    params = {
                        'calendarId': cal_id,
                        'maxResults': 250,
                        'singleEvents': True,
                        'orderBy': 'startTime'
                    }
                    # Nếu bạn muốn bật lại bộ lọc thời gian sau khi test xong thì mở lại đoạn này:
                    # if time_min: params['timeMin'] = time_min
                    # if time_max: params['timeMax'] = time_max
                        
                    events_result = service.events().list(**params).execute()
                    items = events_result.get('items', [])
                    print(f" -> Lịch '{cal_summary}' có {len(items)} sự kiện.")
                    
                    for item in items:
                        start = item['start'].get('dateTime', item['start'].get('date'))
                        end = item['end'].get('dateTime', item['end'].get('date'))
                        all_google_events.append({
                            "id": item['id'],
                            "title": item.get('summary', 'Không có tiêu đề'),
                            "start": start,
                            "end": end,
                            "location": item.get('location', ''),
                            "is_google": True,
                            "calendar_name": cal_summary
                        })
                except Exception as sub_err:
                    print(f" -> Bỏ qua lịch '{cal_summary}' do lỗi: {sub_err}")
                    
            return jsonify(all_google_events)
            
        except Exception as e:
            print("Lỗi đồng bộ Google Calendar:", e)
            return jsonify([])

# API thêm sự kiện thủ công (Chỉ dành cho tài khoản nội bộ)
@app.route('/api/calendar-events', methods=['POST'])
def add_calendar_event():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    username = session['user']['email']
    data = request.json
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO calendar_events (username, title, event_date, start_time, end_time, location, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        username,
        data.get('title'),
        data.get('event_date'),
        data.get('start_time'),
        data.get('end_time'),
        data.get('location', ''),
        data.get('description', '')
    ))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return jsonify({"success": True, "id": str(new_id)})

# API xóa sự kiện thủ công
@app.route('/api/calendar-events/<int:event_id>', methods=['DELETE'])
def delete_calendar_event(event_id):
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    username = session['user']['email']
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM calendar_events WHERE id = ? AND username = ?', (event_id, username))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

if __name__ == '__main__':
    init_db()
    app.run(debug=True)