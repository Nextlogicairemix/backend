from flask import Flask, request, jsonify, render_template, session
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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', '2f28a2528a8149a1333078c5985fc3f55508bba01390828e')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(os.getcwd(), 'flask_session')
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'

CORS(app, supports_credentials=True, origins=[
    'https://nextlogicai.com',
    'https://www.nextlogicai.com',
    'https://68fc3fe5fdf0b300837be57c--mellifluous-crumble-aa751e.netlify.app',
    'https://*.netlify.app',
    'http://localhost:3000',
    'http://localhost:5000'
])

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# THREE-TIER SYSTEM
PREMIUM_OPTIONS = [
    'email', 'ad', 'blog', 'story', 'smalltalk', 
    'interview', 'salespitch', 'thanks',
    'followup', 'apology', 'reminder', 'agenda'
]

FREE_AND_GUEST_OPTIONS = [
    'tweet', 'linkedin', 'instagram', 
    'youtube', 'press', 'casual'
]

# Initialize session
try:
    Session(app)
    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    print(f"✅ Session initialized")
except Exception as e:
    print(f"❌ Failed to initialize session: {str(e)}", file=sys.stderr)
    sys.exit(1)

def get_db_connection():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(db_url)

def init_db():
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    paid BOOLEAN DEFAULT FALSE,
                    failed_attempts INTEGER DEFAULT 0,
                    lock_until TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            try:
                cur.execute("ALTER TABLE users DROP COLUMN IF EXISTS uses")
            except:
                pass
            cur.execute("""
                CREATE TABLE IF NOT EXISTS login_logs (
                    id SERIAL PRIMARY KEY,
                    username TEXT,
                    ip TEXT,
                    success BOOLEAN,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
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
            print("✅ Database initialized")
    except Exception as e:
        print(f"❌ Database init failed: {str(e)}", file=sys.stderr)
        sys.exit(1)

init_db()

def send_email_notification(name, email, message):
    """Send email notification when someone contacts you"""
    try:
        # Get email configuration from environment variables
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        sender_email = os.getenv('SENDER_EMAIL')  # Your email
        sender_password = os.getenv('SENDER_PASSWORD')  # App password
        recipient_email = os.getenv('RECIPIENT_EMAIL', sender_email)  # Where to receive contact messages
        
        if not sender_email or not sender_password:
            print("⚠️ Email not configured. Set SENDER_EMAIL and SENDER_PASSWORD in .env")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'NextLogicAI Contact: {name}'
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Reply-To'] = email
        
        # Email body
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2 style="color: #8b5cf6;">New Contact Form Submission</h2>
            <p><strong>From:</strong> {name}</p>
            <p><strong>Email:</strong> {email}</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <hr>
            <h3>Message:</h3>
            <p>{message.replace(chr(10), '<br>')}</p>
            <hr>
            <p style="color: #666; font-size: 12px;">
                Reply directly to this email to respond to {name}
            </p>
        </body>
        </html>
        """
        
        text = f"""
        New Contact Form Submission
        
        From: {name}
        Email: {email}
        Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        
        Message:
        {message}
        
        Reply to {email} to respond.
        """
        
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        
        print(f"✅ Email sent for contact from {name}")
        return True
        
    except Exception as e:
        print(f"❌ Email send failed: {str(e)}", file=sys.stderr)
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check_session')
def check_session():
    user = session.get('user')
    if not user:
        return jsonify({'logged_in': False, 'is_paid': False, 'tier': 'guest'})
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT paid FROM users WHERE username = %s", (user,))
            user_data = cur.fetchone()
            
            if user_data:
                return jsonify({
                    'logged_in': True,
                    'is_paid': user_data['paid'],
                    'tier': 'premium' if user_data['paid'] else 'free'
                })
            else:
                session.pop('user', None)
                return jsonify({'logged_in': False, 'is_paid': False, 'tier': 'guest'})
    except Exception as e:
        print(f"❌ Session check error: {str(e)}", file=sys.stderr)
        return jsonify({'logged_in': False, 'is_paid': False, 'tier': 'guest'})

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'GET':
        return render_template('login.html', hcaptcha_site_key=os.getenv('HCAPTCHA_SITE_KEY'))
    
    try:
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        ip = request.remote_addr
        
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        
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
            cur.execute("""
                SELECT password_hash, paid, failed_attempts, lock_until 
                FROM users WHERE username = %s
            """, (username,))
            user_data = cur.fetchone()
            
            if not user_data:
                cur.execute("INSERT INTO login_logs (username, ip, success) VALUES (%s, %s, %s)",
                          (username, ip, False))
                conn.commit()
                return jsonify({'error': 'Invalid credentials'}), 401
            
            if user_data['lock_until'] and user_data['lock_until'] > datetime.now():
                return jsonify({'error': 'Account locked. Try again later.'}), 429
            
            if checkpw(password.encode(), user_data['password_hash'].encode()):
                cur.execute("UPDATE users SET failed_attempts = 0, lock_until = NULL WHERE username = %s", (username,))
                cur.execute("INSERT INTO login_logs (username, ip, success) VALUES (%s, %s, %s)",
                          (username, ip, True))
                conn.commit()
                
                session['user'] = username
                return jsonify({
                    'message': 'Login successful',
                    'is_paid': user_data['paid'],
                    'tier': 'premium' if user_data['paid'] else 'free'
                })
            else:
                new_attempts = user_data['failed_attempts'] + 1
                lock_until = datetime.now() + timedelta(minutes=15) if new_attempts >= 5 else None
                
                cur.execute("UPDATE users SET failed_attempts = %s, lock_until = %s WHERE username = %s",
                          (new_attempts, lock_until, username))
                cur.execute("INSERT INTO login_logs (username, ip, success) VALUES (%s, %s, %s)",
                          (username, ip, False))
                conn.commit()
                return jsonify({'error': 'Invalid credentials'}), 401
                
    except Exception as e:
        print(f"❌ Login error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def register():
    if request.method == 'GET':
        return render_template('register.html', hcaptcha_site_key=os.getenv('HCAPTCHA_SITE_KEY'))
    
    try:
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
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
            cur.execute("SELECT username FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return jsonify({'error': 'Username already exists'}), 400
            
            hashed_password = hashpw(password.encode(), gensalt()).decode()
            cur.execute("INSERT INTO users (username, password_hash, paid) VALUES (%s, %s, %s)",
                      (username, hashed_password, False))
            conn.commit()
            
            return jsonify({'message': 'Registration successful', 'redirect': '/login'})
            
    except Exception as e:
        print(f"❌ Registration error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/logout')
def logout():
    session.pop('user', None)
    return jsonify({'message': 'Logged out'})

@app.route('/remix', methods=['POST'])
@limiter.limit("30 per hour")
def remix():
    try:
        user = session.get('user')
        data = request.get_json()
        prompt = data.get('prompt', '').strip()
        remix_type = data.get('remix-type', 'tweet')
        is_guest = data.get('is_guest', False)
        
        if not prompt:
            return jsonify({'error': 'Prompt is required'}), 400
        
        # Check if premium feature
        if remix_type in PREMIUM_OPTIONS:
            if not user:
                return jsonify({'error': 'Please log in to access this feature', 'requiresPremium': True}), 401
            
            with get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute("SELECT paid FROM users WHERE username = %s", (user,))
                user_data = cur.fetchone()
                
                if not user_data or not user_data['paid']:
                    return jsonify({'error': 'Premium subscription required', 'requiresPremium': True}), 403
        
        # Check if valid feature type
        if remix_type not in FREE_AND_GUEST_OPTIONS and remix_type not in PREMIUM_OPTIONS:
            return jsonify({'error': 'Invalid content type'}), 400
        
        # For guests, frontend handles the 3-use limit via localStorage
        # Backend just processes the request
        if is_guest and not user:
            # Guest user - allow the request (frontend tracks usage)
            pass
        elif not user:
            return jsonify({'error': 'Please log in or use guest mode'}), 401
        
        # Call Gemini API
        api_key = os.getenv('GENERATIVE_API_KEY')
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        
        type_prompts = {
            'tweet': f"Convert this into an engaging Twitter thread with 3-5 tweets. Use emojis and make it punchy:\n\n{prompt}",
            'email': f"Rewrite this as a professional, clear, and polished email:\n\n{prompt}",
            'ad': f"Transform this into persuasive, catchy ad copy that drives action:\n\n{prompt}",
            'linkedin': f"Rewrite this as a professional LinkedIn post with insights:\n\n{prompt}",
            'blog': f"Expand this into an SEO-friendly blog post with headers and paragraphs:\n\n{prompt}",
            'instagram': f"Create an engaging Instagram caption with relevant hashtags:\n\n{prompt}",
            'youtube': f"Write an optimized YouTube description with timestamps:\n\n{prompt}",
            'press': f"Format this as a professional press release announcement:\n\n{prompt}",
            'story': f"Rewrite this as an engaging narrative story:\n\n{prompt}",
            'casual': f"Rewrite this in a relaxed, fun, casual tone:\n\n{prompt}",
            'followup': f"Write a warm, casual follow-up message:\n\n{prompt}",
            'apology': f"Write a sincere and brief apology:\n\n{prompt}",
            'reminder': f"Write a direct and clear urgent reminder:\n\n{prompt}",
            'smalltalk': f"Create an easy, approachable small talk starter:\n\n{prompt}",
            'agenda': f"Write a focused, engaging meeting agenda teaser:\n\n{prompt}",
            'interview': f"Create a confident, concise job interview pitch:\n\n{prompt}",
            'salespitch': f"Write a persuasive, smooth sales pitch opener:\n\n{prompt}",
            'thanks': f"Write a grateful, natural casual thank-you speech:\n\n{prompt}"
        }
        
        formatted_prompt = type_prompts.get(remix_type, f"Rewrite this:\n\n{prompt}")
        
        payload = {"contents": [{"parts": [{"text": formatted_prompt}]}]}
        response = requests.post(url, json=payload, timeout=120)
        
        if response.status_code != 200:
            error_msg = response.json().get('error', {}).get('message', 'API error')
            return jsonify({'error': error_msg}), response.status_code
        
        result = response.json()
        if not result.get('candidates'):
            return jsonify({'error': 'No response from AI'}), 500
        
        output = result['candidates'][0]['content']['parts'][0]['text']
        return jsonify({'output': output})
            
    except requests.Timeout:
        return jsonify({'error': 'Request timeout. Please try again.'}), 504
    except Exception as e:
        print(f"❌ Remix error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/update_subscription', methods=['POST'])
def update_subscription():
    try:
        user = session.get('user')
        if not user:
            return jsonify({'error': 'Not logged in'}), 401
        
        subscription_id = request.json.get('subscriptionID')
        
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET paid = TRUE WHERE username = %s", (user,))
            conn.commit()
        
        print(f"✅ Subscription activated for: {user}")
        return jsonify({'message': 'Subscription activated!'})
        
    except Exception as e:
        print(f"❌ Subscription error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/contact', methods=['POST'])
@limiter.limit("5 per hour")
def contact():
    try:
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        message = request.form.get('message', '').strip()
        
        if not all([name, email, message]):
            return jsonify({'error': 'All fields are required'}), 400
        
        # Save to database
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO contacts (name, email, message) VALUES (%s, %s, %s)",
                      (name, email, message))
            conn.commit()
        
        # Send email notification
        email_sent = send_email_notification(name, email, message)
        
        if email_sent:
            print(f"📧 Contact from {name} ({email}) - Email sent")
        else:
            print(f"📧 Contact from {name} ({email}) - Saved to database only")
        
        return jsonify({'message': 'Message sent successfully!'})
        
    except Exception as e:
        print(f"❌ Contact error: {str(e)}", file=sys.stderr)
        return jsonify({'error': 'Server error'}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)