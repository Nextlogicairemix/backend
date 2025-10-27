from flask import Flask, request, jsonify, session
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
from datetime import datetime, timedelta
import secrets
import string

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-this')

# Session configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # ← CRITICAL for cross-origin
app.config['SESSION_COOKIE_NAME'] = 'nextlogicai_session'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours

Session(app)

CORS(app, resources={
    r"/*": {
        "origins": ["https://nextlogicai.com", "https://www.nextlogicai.com", "https://nextlogicai.netlify.app"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }
})

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    fullname VARCHAR(100),
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    birthdate DATE,
                    password VARCHAR(255) NOT NULL,
                    is_premium BOOLEAN DEFAULT FALSE,
                    premium_expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    referral_code VARCHAR(20) UNIQUE,
                    referred_by INTEGER,
                    referral_credits INTEGER DEFAULT 0,
                    uses_left INTEGER DEFAULT 3,
                    FOREIGN KEY (referred_by) REFERENCES users(id)
                )
            """)
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS remix_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    original_text TEXT NOT NULL,
                    remixed_text TEXT NOT NULL,
                    remix_type VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id INTEGER NOT NULL,
                    referee_id INTEGER NOT NULL,
                    referral_code VARCHAR(20) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    reward_given BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (referrer_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (referee_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            
            conn.commit()
            cur.close()
            print("Database initialized")
        except Exception as e:
            print(f"DB init error: {e}")
        finally:
            conn.close()

def generate_referral_code(username):
    base = username[:5].upper()
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"{base}{random_part}"

init_db()

@app.route('/')
def index():
    return jsonify({"message": "NextLogicAI Backend API", "status": "running"})

@app.route('/register', methods=['POST'])
@limiter.limit("10 per hour")
def register():
    data = request.get_json()
    fullname = data.get('fullname')
    username = data.get('username')
    email = data.get('email')
    birthdate = data.get('birthdate')
    password = data.get('password')
    referral_code = data.get('referral_code')
    
    if not all([fullname, username, email, birthdate, password]):
        return jsonify({"error": "Missing required fields"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        
        referrer_id = None
        if referral_code:
            cur.execute("SELECT id FROM users WHERE referral_code = %s", (referral_code,))
            referrer = cur.fetchone()
            if referrer:
                referrer_id = referrer['id']
        
        new_referral_code = generate_referral_code(username)
        
        cur.execute("""
            INSERT INTO users (fullname, username, email, birthdate, password, referral_code, referred_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (fullname, username, email, birthdate, password, new_referral_code, referrer_id))
        
        new_user_id = cur.fetchone()['id']
        
        if referrer_id:
            cur.execute("""
                INSERT INTO referrals (referrer_id, referee_id, referral_code, status)
                VALUES (%s, %s, %s, 'pending')
            """, (referrer_id, new_user_id, referral_code))
        
        conn.commit()
        cur.close()
        
        session['user_id'] = new_user_id
        session['username'] = username
        session['is_premium'] = False
        session['referral_code'] = new_referral_code
        
        return jsonify({
            "message": "Registration successful",
            "user_id": new_user_id,
            "referral_code": new_referral_code
        }), 201
        
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Username or email already exists"}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/login', methods=['POST'])
@limiter.limit("20 per hour")
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not all([username, password]):
        return jsonify({"error": "Missing username or password"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, email, is_premium, premium_expires_at, referral_code, uses_left
            FROM users 
            WHERE username = %s AND password = %s
        """, (username, password))
        
        user = cur.fetchone()
        cur.close()
        
        if user:
            is_premium = user['is_premium']
            if is_premium and user['premium_expires_at']:
                if datetime.now() > user['premium_expires_at']:
                    is_premium = False
                    cur = conn.cursor()
                    cur.execute("UPDATE users SET is_premium = FALSE WHERE id = %s", (user['id'],))
                    conn.commit()
                    cur.close()
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_premium'] = is_premium
            session['referral_code'] = user['referral_code']
            
            return jsonify({
                "message": "Login successful",
                "user": {
                    "id": user['id'],
                    "username": user['username'],
                    "email": user['email'],
                    "is_premium": is_premium,
                    "referral_code": user['referral_code']
                },
                "uses_left": user['uses_left'] if not is_premium else 'unlimited',
                "is_paid": is_premium
            }), 200
        else:
            return jsonify({"error": "Invalid credentials"}), 401
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200

@app.route('/check_session', methods=['GET'])
def check_session():
    if 'user_id' in session:
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT uses_left, is_premium FROM users WHERE id = %s", (session['user_id'],))
                user = cur.fetchone()
                cur.close()
                conn.close()
                
                return jsonify({
                    "logged_in": True,
                    "user_id": session['user_id'],
                    "username": session['username'],
                    "is_premium": session.get('is_premium', False),
                    "is_paid": session.get('is_premium', False),
                    "referral_code": session.get('referral_code'),
                    "uses_left": user['uses_left'] if user and not user['is_premium'] else 'unlimited'
                }), 200
            except Exception as e:
                conn.close()
    
    return jsonify({
        "logged_in": False,
        "uses_left": 3
    }), 200

@app.route('/remix', methods=['POST'])
@limiter.limit("20 per hour")
def remix():
    data = request.get_json()
    content = data.get('content', '').strip()
    remix_type = data.get('style', 'tweet')  # Changed to match frontend
    
    if not content:
        return jsonify({"error": "No content provided"}), 400
    
    # Check if user is logged in or using guest quota
    user_id = session.get('user_id')
    is_premium = False
    
    if user_id:
        # Logged-in user - check their uses_left in database
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database error"}), 500
        
        try:
            cur = conn.cursor()
            cur.execute("SELECT uses_left, is_premium FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            cur.close()
            
            if not user:
                conn.close()
                return jsonify({"error": "User not found"}), 404
            
            uses_left, is_premium = user['uses_left'], user['is_premium']
            
            # Premium users have unlimited uses
            if not is_premium:
                if uses_left <= 0:
                    conn.close()
                    return jsonify({
                        "error": "No remixes left. Upgrade to premium for unlimited remixes!",
                        "upgrade_required": True
                    }), 403
                
                # Decrement uses_left for non-premium users
                cur = conn.cursor()
                cur.execute("UPDATE users SET uses_left = uses_left - 1 WHERE id = %s", (user_id,))
                conn.commit()
                cur.close()
                uses_left -= 1
            
            conn.close()
        except Exception as e:
            conn.rollback()
            conn.close()
            return jsonify({"error": str(e)}), 500
    else:
        # Guest user - use session-based counter
        if 'guest_uses_left' not in session:
            session['guest_uses_left'] = 3  # Initialize with 3 free uses
        
        uses_left = session['guest_uses_left']
        
        if uses_left <= 0:
            return jsonify({
                "error": "You've used all 3 free remixes! Sign up for more.",
                "signup_required": True
            }), 403
        
        # Decrement guest counter
        session['guest_uses_left'] = uses_left - 1
        uses_left -= 1
    
    # Call Google Gemini API to remix content
    try:
        gemini_api_key = os.environ.get('GEMINI_API_KEY')
        if not gemini_api_key:
            return jsonify({"error": "Gemini API not configured"}), 500
        
        # Remix type prompts matching your frontend options
        remix_prompts = {
            'tweet': 'Convert this into an engaging Twitter thread with 3-5 tweets. Use emojis and make it conversational.',
            'linkedin': 'Rewrite this as a professional LinkedIn post with a hook, valuable insights, and a call-to-action.',
            'instagram': 'Transform this into an Instagram caption with emojis, hashtags, and an engaging hook.',
            'facebook': 'Rewrite this as a Facebook post that encourages engagement and comments.',
            'reddit': 'Convert this into a Reddit post with a catchy title and detailed explanation.',
            'youtube': 'Create a YouTube video description with timestamps, keywords, and SEO optimization.',
            'tiktok': 'Write a short, catchy TikTok caption with trending hashtags.',
            'pinterest': 'Create a Pinterest description that drives clicks with keywords and benefits.',
            'summary': 'Summarize this content in 2-3 concise sentences.',
            'bullets': 'Convert this into clear bullet points highlighting the key information.',
            'expand': 'Expand this content with more details, examples, and explanations.',
            'email': 'Write a professional email based on this content with a clear subject line.',
            'ad': 'Create compelling ad copy with a strong headline and call-to-action.',
            'blog': 'Expand this into a full blog post with introduction, body paragraphs, and conclusion.',
            'story': 'Rewrite this as an engaging narrative story.',
            'smalltalk': 'Turn this into casual small talk conversation starters.',
            'salespitch': 'Create a persuasive sales pitch highlighting benefits and urgency.',
            'thanks': 'Write a warm thank-you message based on this content.',
            'followup': 'Create a friendly follow-up message.',
            'apology': 'Write a sincere apology message.',
            'reminder': 'Create an urgent but polite reminder message.',
            'agenda': 'Convert this into a meeting agenda with time allocations.',
            'interview': 'Create a compelling job interview pitch.'
        }
        
        prompt = remix_prompts.get(remix_type, remix_prompts['tweet'])
        
            response = requests.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_api_key}',
                headers={'Content-Type': 'application/json'},
                json={
                    'contents': [{
                        'parts': [{
                            'text': f"{prompt}\n\nContent to transform:\n{content}"
                        }]
                    }],
                    'generationConfig': {
                        'temperature': 0.7,
                        'maxOutputTokens': 5000
                    }
                },
                timeout=120
            )
        
        if response.status_code == 200:
            result = response.json()
            
            # Extract text from Gemini response
            if 'candidates' in result and len(result['candidates']) > 0:
                remixed_content = result['candidates'][0]['content']['parts'][0]['text']
            else:
                return jsonify({"error": "No response from AI"}), 500
            
            # Save to history if user is logged in
            if user_id:
                try:
                    conn = get_db_connection()
                    if conn:
                        cur = conn.cursor()
                        cur.execute("""
                            INSERT INTO remix_history (user_id, original_text, remixed_text, remix_type)
                            VALUES (%s, %s, %s, %s)
                        """, (user_id, content, remixed_content, remix_type))
                        conn.commit()
                        cur.close()
                        conn.close()
                except:
                    pass  # Don't fail if history save fails
            
            return jsonify({
                "output": remixed_content,  # Changed to 'output' to match frontend
                "uses_left": uses_left if not is_premium else 'unlimited',
                "is_guest": user_id is None,
                "is_premium": is_premium
            }), 200
        else:
            error_msg = response.json() if response.text else "Unknown error"
            print(f"Gemini API error: {response.status_code} - {error_msg}")
            return jsonify({"error": "Failed to remix content. Please try again."}), 500
            
    except requests.exceptions.Timeout:
        return jsonify({"error": "AI is taking too long. Please try with shorter text."}), 504
    except Exception as e:
        print(f"Remix error: {e}")
        return jsonify({"error": "An error occurred during remix"}), 500
    finally:
        conn.close()

@app.route('/contact', methods=['POST'])
@limiter.limit("10 per hour")
def contact():
    name = request.form.get('name')
    email = request.form.get('email')
    message = request.form.get('message')
    
    if not all([name, email, message]):
        return jsonify({"error": "All fields required"}), 400
    
    # Validate email format
    import re
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return jsonify({"error": "Invalid email address"}), 400
    
    # Send email via Mailgun
    try:
        mailgun_domain = os.environ.get('MAILGUN_DOMAIN')
        mailgun_api_key = os.environ.get('MAILGUN_API_KEY')
        recipient_email = os.environ.get('CONTACT_EMAIL')
        
        if not all([mailgun_domain, mailgun_api_key, recipient_email]):
            print("Mailgun not configured")
            return jsonify({"error": "Email service not configured"}), 500
        
        response = requests.post(
            f"https://api.mailgun.net/v3/{mailgun_domain}/messages",
            auth=("api", mailgun_api_key),
            data={
                "from": f"NextLogicAI Contact <noreply@{mailgun_domain}>",
                "to": recipient_email,
                "reply-to": email,
                "subject": f"Contact Form: {name}",
                "html": f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
        <h2 style="color: #6366f1;">New Contact Form Submission</h2>
        
        <div style="background: #f9fafb; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <p><strong>Name:</strong> {name}</p>
            <p><strong>Email:</strong> <a href="mailto:{email}">{email}</a></p>
        </div>
        
        <div style="background: #fff; padding: 15px; border: 1px solid #e5e7eb; border-radius: 8px;">
            <h3>Message:</h3>
            <p style="white-space: pre-wrap;">{message}</p>
        </div>
    </div>
</body>
</html>
                """
            }
        )
        
        if response.status_code == 200:
            return jsonify({"message": "Message sent successfully!"}), 200
        else:
            print(f"Mailgun error: {response.status_code} - {response.text}")
            return jsonify({"error": "Failed to send message"}), 500
            
    except Exception as e:
        print(f"Contact form error: {e}")
        return jsonify({"error": "Failed to send message"}), 500
    
    return jsonify({"message": "Message received"}), 200

@app.route('/update_subscription', methods=['POST'])
def update_subscription():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json()
    subscription_id = data.get('subscriptionID')
    
    if not subscription_id:
        return jsonify({"error": "No subscription ID"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database error"}), 500
    
    try:
        cur = conn.cursor()
        premium_expires = datetime.now() + timedelta(days=30)
        
        # Get user info for referral check
        cur.execute("SELECT referred_by FROM users WHERE id = %s", (session['user_id'],))
        user = cur.fetchone()
        
        # Update user to premium
        cur.execute("""
            UPDATE users 
            SET is_premium = TRUE, premium_expires_at = %s 
            WHERE id = %s
        """, (premium_expires, session['user_id']))
        
        # If user was referred, reward the referrer
        if user and user['referred_by']:
            referrer_id = user['referred_by']
            
            # Update referral status
            cur.execute("""
                UPDATE referrals 
                SET status = 'completed', completed_at = %s, reward_given = TRUE
                WHERE referee_id = %s AND referrer_id = %s
            """, (datetime.now(), session['user_id'], referrer_id))
            
            # Give referrer 30 days premium
            cur.execute("""
                UPDATE users 
                SET referral_credits = referral_credits + 30,
                    is_premium = TRUE,
                    premium_expires_at = GREATEST(
                        COALESCE(premium_expires_at, CURRENT_TIMESTAMP), 
                        CURRENT_TIMESTAMP
                    ) + INTERVAL '30 days'
                WHERE id = %s
            """, (referrer_id,))
        
        conn.commit()
        cur.close()
        session['is_premium'] = True
        
        return jsonify({"message": "Subscription activated"}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)