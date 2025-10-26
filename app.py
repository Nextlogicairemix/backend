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
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
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
@limiter.limit("100 per hour")
def remix_content():
    data = request.get_json()
    text = data.get('prompt') or data.get('text')
    remix_type = data.get('remix-type') or data.get('type', 'tweet')
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
    
    # Check if user is logged in
    if 'user_id' not in session:
        return jsonify({"error": "Please log in to use this feature"}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("SELECT uses_left, is_premium FROM users WHERE id = %s", (session['user_id'],))
        user = cur.fetchone()
        
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Premium options
        premium_options = ['email', 'ad', 'blog', 'story', 'smalltalk', 'salespitch', 
                          'thanks', 'followup', 'apology', 'reminder', 'agenda', 'interview']
        
        # Check if premium required
        if remix_type in premium_options and not user['is_premium']:
            return jsonify({"error": "Premium subscription required for this feature"}), 403
        
        # Check uses left for non-premium users
        if not user['is_premium'] and user['uses_left'] <= 0:
            return jsonify({"error": "No free remixes left. Please upgrade to premium."}), 403
        
        # TODO: Call your AI API here
        # This is a placeholder
        remixed_text = f"[AI Remixed {remix_type}]: {text[:100]}..."
        
        # Deduct usage for non-premium
        if not user['is_premium']:
            cur.execute("UPDATE users SET uses_left = uses_left - 1 WHERE id = %s RETURNING uses_left", 
                       (session['user_id'],))
            updated_user = cur.fetchone()
            new_uses = updated_user['uses_left']
        else:
            new_uses = 'unlimited'
        
        # Save to history
        cur.execute("""
            INSERT INTO remix_history (user_id, original_text, remixed_text, remix_type)
            VALUES (%s, %s, %s, %s)
        """, (session['user_id'], text, remixed_text, remix_type))
        
        conn.commit()
        cur.close()
        
        return jsonify({
            "output": remixed_text,
            "uses_left": new_uses
        }), 200
        
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
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
    
    # TODO: Send email or save to database
    print(f"Contact from {name} ({email}): {message}")
    
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