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
        "origins": ["https://nextlogicai.com", "nextlogicai.netlify.app"],
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

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in environment variables")
    sys.exit(1)

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

# Initialize database tables
def init_db():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            # Users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    is_premium BOOLEAN DEFAULT FALSE,
                    premium_expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    referral_code VARCHAR(20) UNIQUE,
                    referred_by INTEGER,
                    referral_credits INTEGER DEFAULT 0,
                    FOREIGN KEY (referred_by) REFERENCES users(id)
                )
            """)
            
            # Remix history table
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
            
            # Referrals table
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
            print("Database tables initialized successfully")
        except Exception as e:
            print(f"Error initializing database: {e}")
        finally:
            conn.close()

# Generate unique referral code
def generate_referral_code(username):
    base = username[:5].upper()
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"{base}{random_part}"

# Initialize database on startup
init_db()

@app.route('/')
def index():
    return jsonify({"message": "NextLogicAI Backend API", "status": "running"})

@app.route('/register', methods=['POST'])
@limiter.limit("10 per hour")
def register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    referral_code = data.get('referral_code')
    
    if not all([username, email, password]):
        return jsonify({"error": "Missing required fields"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        
        # Check if referral code is valid
        referrer_id = None
        if referral_code:
            cur.execute("SELECT id FROM users WHERE referral_code = %s", (referral_code,))
            referrer = cur.fetchone()
            if referrer:
                referrer_id = referrer['id']
        
        # Generate unique referral code for new user
        new_referral_code = generate_referral_code(username)
        
        # Create user
        cur.execute("""
            INSERT INTO users (username, email, password, referral_code, referred_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (username, email, password, new_referral_code, referrer_id))
        
        new_user_id = cur.fetchone()['id']
        
        # If there was a referrer, create referral record
        if referrer_id:
            cur.execute("""
                INSERT INTO referrals (referrer_id, referee_id, referral_code, status)
                VALUES (%s, %s, %s, 'pending')
            """, (referrer_id, new_user_id, referral_code))
        
        conn.commit()
        cur.close()
        
        # Set session
        session['user_id'] = new_user_id
        session['username'] = username
        session['is_premium'] = False
        
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
            SELECT id, username, email, is_premium, premium_expires_at, referral_code 
            FROM users 
            WHERE username = %s AND password = %s
        """, (username, password))
        
        user = cur.fetchone()
        cur.close()
        
        if user:
            # Check if premium has expired
            is_premium = user['is_premium']
            if is_premium and user['premium_expires_at']:
                if datetime.now() > user['premium_expires_at']:
                    is_premium = False
                    # Update database
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
                }
            }), 200
        else:
            return jsonify({"error": "Invalid credentials"}), 401
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200

@app.route('/check_session', methods=['GET'])
def check_session():
    if 'user_id' in session:
        return jsonify({
            "logged_in": True,
            "user_id": session['user_id'],
            "username": session['username'],
            "is_premium": session.get('is_premium', False),
            "referral_code": session.get('referral_code')
        }), 200
    return jsonify({"logged_in": False}), 200

@app.route('/remix', methods=['POST'])
@limiter.limit("100 per hour")
def remix_content():
    data = request.get_json()
    text = data.get('text')
    remix_type = data.get('type', 'tweet')
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
    
    # Check if user is logged in and premium
    is_premium = session.get('is_premium', False)
    
    try:
        # Call your AI API here
        # This is a placeholder - replace with your actual AI service
        response = requests.post(
            'YOUR_AI_API_ENDPOINT',
            json={"text": text, "type": remix_type},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({
                "remixed_text": result.get('remixed_text'),
                "is_premium": is_premium
            }), 200
        else:
            return jsonify({"error": "AI service error"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/save_remix', methods=['POST'])
def save_remix():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.get_json()
    original_text = data.get('original_text')
    remixed_text = data.get('remixed_text')
    remix_type = data.get('remix_type')
    
    if not all([original_text, remixed_text, remix_type]):
        return jsonify({"error": "Missing required fields"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO remix_history (user_id, original_text, remixed_text, remix_type)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
        """, (session['user_id'], original_text, remixed_text, remix_type))
        
        result = cur.fetchone()
        conn.commit()
        cur.close()
        
        return jsonify({
            "message": "Remix saved successfully",
            "remix_id": result['id'],
            "created_at": result['created_at'].isoformat()
        }), 201
        
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/get_history', methods=['GET'])
def get_history():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    limit = request.args.get('limit', 50, type=int)
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, original_text, remixed_text, remix_type, created_at
            FROM remix_history
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (session['user_id'], limit))
        
        history = cur.fetchall()
        cur.close()
        
        # Convert datetime to string
        for item in history:
            item['created_at'] = item['created_at'].isoformat()
        
        return jsonify({"history": history}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/get_referral_data', methods=['GET'])
def get_referral_data():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        cur = conn.cursor()
        
        # Get user's referral code and credits
        cur.execute("""
            SELECT referral_code, referral_credits
            FROM users
            WHERE id = %s
        """, (session['user_id'],))
        user_data = cur.fetchone()
        
        # Get referral statistics
        cur.execute("""
            SELECT 
                COUNT(*) as total_referrals,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_referrals,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_referrals
            FROM referrals
            WHERE referrer_id = %s
        """, (session['user_id'],))
        stats = cur.fetchone()
        
        cur.close()
        
        return jsonify({
            "referral_code": user_data['referral_code'],
            "referral_credits": user_data['referral_credits'],
            "total_referrals": stats['total_referrals'] or 0,
            "completed_referrals": stats['completed_referrals'] or 0,
            "pending_referrals": stats['pending_referrals'] or 0
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/subscription/webhook', methods=['POST'])
def subscription_webhook():
    """Handle Stripe or payment provider webhook for subscription events"""
    data = request.get_json()
    
    # Verify webhook signature (implement based on your payment provider)
    
    event_type = data.get('type')
    user_email = data.get('customer_email')
    
    if event_type == 'checkout.session.completed':
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        try:
            cur = conn.cursor()
            
            # Get user ID
            cur.execute("SELECT id, referred_by FROM users WHERE email = %s", (user_email,))
            user = cur.fetchone()
            
            if user:
                user_id = user['id']
                referrer_id = user['referred_by']
                
                # Update user to premium
                premium_expires = datetime.now() + timedelta(days=30)
                cur.execute("""
                    UPDATE users 
                    SET is_premium = TRUE, premium_expires_at = %s 
                    WHERE id = %s
                """, (premium_expires, user_id))
                
                # If user was referred, reward the referrer
                if referrer_id:
                    # Update referral status
                    cur.execute("""
                        UPDATE referrals 
                        SET status = 'completed', completed_at = %s, reward_given = TRUE
                        WHERE referee_id = %s AND referrer_id = %s
                    """, (datetime.now(), user_id, referrer_id))
                    
                    # Give referrer 30 days of premium credits
                    cur.execute("""
                        UPDATE users 
                        SET referral_credits = referral_credits + 30
                        WHERE id = %s
                    """, (referrer_id,))
                
                conn.commit()
                cur.close()
                
            conn.close()
            return jsonify({"message": "Webhook processed"}), 200
            
        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            if conn:
                conn.close()
    
    return jsonify({"message": "Event not handled"}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)