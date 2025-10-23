from flask import Flask, request, jsonify, render_template, session, make_response
from flask_cors import CORS
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
import os
import sys
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from bcrypt import hashpw, gensalt, checkpw
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', '2f28a2528a8149a1333078c5985fc3f55508bba01390828e')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(os.getcwd(), 'flask_session')
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# CORS configuration for Netlify frontend
CORS(app, supports_credentials=True, origins=[
    'https://nextlogicai.com',
    'https://*.netlify.app',
    'http://localhost:*'
])

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Initialize session
try:
    Session(app)
    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    print(f"✅ Session initialized: {app.config['SESSION_FILE_DIR']}")
except Exception as e:
    print(f"❌ Failed to initialize session: {str(e)}", file=sys.stderr)
    sys.exit(1)

# Database connection
def get_db_connection():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(db_url)

# Initialize database
def init_db():
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Create users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    paid BOOLEAN DEFAULT FALSE,
                    uses INTEGER DEFAULT 3,
                    failed_attempts INTEGER DEFAULT 0,
                    lock_until TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create logs table for security
            cur.execute("""
                CREATE TABLE IF NOT EXISTS login_logs (
                    id SERIAL PRIMARY KEY,
                    username TEXT,
                    ip TEXT,
                    success BOOLEAN,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create contacts table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization failed: {str(e)}", file=sys.stderr)
        sys.exit(1)

# Initialize on startup
init_db()

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check_session')
def check_session():
    """Check if user is logged in and return their status"""
    user = session.get('user')
    
    if not user:
        return jsonify({'logged_in': False, 'uses_left': 3})
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT paid, uses FROM users WHERE username = %s", (user,))
            user_data = cur.fetchone()
            
            if user_data:
                return jsonify({
                    'logged_in': True,
                    'is_paid': user_data['paid'],
                    'uses_left': user_data['uses']
                })
            else:
                session.pop('user', None)
                return jsonify({'logged_in': False, 'uses_left': 3})
    except Exception as e:
        print(f"❌ Session check error: {str(e)}", file=sys.stderr)
        return jsonify({'logged_in': False, 'uses_left': 3})

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    """Handle user login with rate limiting and hCaptcha"""
    if request.method == 'GET':
        return render_template('login.html', 
                             hcaptcha_site_key=os.getenv('HCAPTCHA_SITE_KEY'))
    
    try:
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        ip = request.remote_addr
        
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        
        # Verify hCaptcha
        hcaptcha_response = request.form.get('h-captcha-response')
        if not hcaptcha_response:
            return jsonify({'error': 'Please complete the hCaptcha'}), 400
        
        secret_key = os.getenv('HCAPTCHA_SECRET')
        verify_response = requests.post('https://hcaptcha.com/siteverify', data={
            'secret': secret_key,
            'response': hcaptcha_response
        })
        
        if not verify_response.json().get('success'):
            return jsonify({'error': 'Invalid hCaptcha'}), 400
        
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get user data
            cur.execute("""
                SELECT password_hash, paid, uses, failed_attempts, lock_until 
                FROM users WHERE username = %s
            """, (username,))
            user_data = cur.fetchone()
            
            if not user_data:
                # Log failed attempt
                cur.execute("""
                    INSERT INTO login_logs (username, ip, success) 
                    VALUES (%s, %s, %s)
                """, (username, ip, False))
                conn.commit()
                return jsonify({'error': 'Invalid credentials'}), 401
            
            # Check if account is locked
            if user_data['lock_until'] and user_data['lock_until'] > datetime.now():
                return jsonify({'error': 'Account locked. Try again later.'}), 429
            
            # Verify password
            if checkpw(password.encode(), user_data['password_hash'].encode()):
                # Success - reset failed attempts
                cur.execute("""
                    UPDATE users 
                    SET failed_attempts = 0, lock_until = NULL 
                    WHERE username = %s
                """, (username,))
                
                cur.execute("""
                    INSERT INTO login_logs (username, ip, success) 
                    VALUES (%s, %s, %s)
                """, (username, ip, True))
                conn.commit()
                
                session['user'] = username
                return jsonify({
                    'message': 'Login successful',
                    'is_paid': user_data['paid'],
                    'uses_left': user_data['uses']
                })
            else:
                # Failed login - increment attempts
                new_attempts = user_data['failed_attempts'] + 1
                lock_until = None
                
                if new_attempts >= 5:
                    lock_until = datetime.now() + timedelta(minutes=15)
                
                cur.execute("""
                    UPDATE users 
                    SET failed_attempts = %s, lock_until = %s 
                    WHERE username = %s
                """, (new_attempts, lock_until, username))
                
                cur.execute("""
                    INSERT INTO login_logs (username, ip, success) 
                    VALUES (%s, %s, %s)
                """, (username, ip, False))
                conn.commit()
                
                return jsonify({'error': 'Invalid credentials'}), 401
                
    except Exception as e:
        print(f"❌ Login error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def register():
    """Handle user registration"""
    if request.method == 'GET':
        return render_template('register.html',
                             hcaptcha_site_key=os.getenv('HCAPTCHA_SITE_KEY'))
    
    try:
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        # Verify hCaptcha
        hcaptcha_response = request.form.get('h-captcha-response')
        if not hcaptcha_response:
            return jsonify({'error': 'Please complete the hCaptcha'}), 400
        
        secret_key = os.getenv('HCAPTCHA_SECRET')
        verify_response = requests.post('https://hcaptcha.com/siteverify', data={
            'secret': secret_key,
            'response': hcaptcha_response
        })
        
        if not verify_response.json().get('success'):
            return jsonify({'error': 'Invalid hCaptcha'}), 400
        
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Check if username exists
            cur.execute("SELECT username FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return jsonify({'error': 'Username already exists'}), 400
            
            # Create user
            hashed_password = hashpw(password.encode(), gensalt()).decode()
            cur.execute("""
                INSERT INTO users (username, password_hash, paid, uses) 
                VALUES (%s, %s, %s, %s)
            """, (username, hashed_password, False, 3))
            conn.commit()
            
            return jsonify({
                'message': 'Registration successful',
                'redirect': '/login'
            })
            
    except Exception as e:
        print(f"❌ Registration error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/logout')
def logout():
    """Handle user logout"""
    session.pop('user', None)
    return jsonify({'message': 'Logged out'})

@app.route('/remix', methods=['POST'])
@limiter.limit("30 per hour")
def remix():
    """Handle content remixing with AI"""
    try:
        user = session.get('user')
        
        if not user:
            return jsonify({'error': 'Please log in to remix content'}), 401
        
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT paid, uses FROM users WHERE username = %s", (user,))
            user_data = cur.fetchone()
            
            if not user_data:
                return jsonify({'error': 'User not found'}), 404
            
            # Check if user has remixes left
            if not user_data['paid'] and user_data['uses'] <= 0:
                return jsonify({'error': 'No free remixes left!'}), 403
            
            # Get prompt and type
            data = request.get_json()
            prompt = data.get('prompt', '').strip()
            remix_type = data.get('remix-type', 'blog')
            
            if not prompt:
                return jsonify({'error': 'Prompt is required'}), 400
            
            # Call Gemini API
            api_key = os.getenv('GENERATIVE_API_KEY')
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": f"Rewrite this as a {remix_type}: {prompt}"}]
                }]
            }
            
            response = requests.post(url, json=payload, timeout=120)
            
            if response.status_code != 200:
                error_msg = response.json().get('error', {}).get('message', 'API error')
                return jsonify({'error': error_msg}), response.status_code
            
            result = response.json()
            
            if not result.get('candidates'):
                return jsonify({'error': 'No response from AI'}), 500
            
            output = result['candidates'][0]['content']['parts'][0]['text']
            
            # Deduct usage if not paid
            new_uses = user_data['uses']
            if not user_data['paid']:
                new_uses = user_data['uses'] - 1
                cur.execute("""
                    UPDATE users SET uses = %s WHERE username = %s
                """, (new_uses, user))
                conn.commit()
            
            return jsonify({
                'output': output,
                'uses_left': new_uses if not user_data['paid'] else 'unlimited'
            })
            
    except requests.Timeout:
        return jsonify({'error': 'Request timeout. Please try again.'}), 504
    except Exception as e:
        print(f"❌ Remix error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/update_subscription', methods=['POST'])
def update_subscription():
    """Handle subscription upgrade via PayPal"""
    try:
        user = session.get('user')
        
        if not user:
            return jsonify({'error': 'Not logged in'}), 401
        
        subscription_id = request.json.get('subscriptionID')
        
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE users SET paid = TRUE WHERE username = %s
            """, (user,))
            conn.commit()
        
        return jsonify({'message': 'Subscription activated!'})
        
    except Exception as e:
        print(f"❌ Subscription error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/contact', methods=['POST'])
@limiter.limit("5 per hour")
def contact():
    """Handle contact form submissions"""
    try:
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        message = request.form.get('message', '').strip()
        
        if not all([name, email, message]):
            return jsonify({'error': 'All fields are required'}), 400
        
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO contacts (name, email, message) 
                VALUES (%s, %s, %s)
            """, (name, email, message))
            conn.commit()
        
        print(f"📧 Contact from {name} ({email}): {message[:50]}...")
        return jsonify({'message': 'Message sent successfully!'})
        
    except Exception as e:
        print(f"❌ Contact error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

# Health check for monitoring
@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)