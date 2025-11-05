from flask import Flask
from flask_cors import CORS
from flask_login import LoginManager
from models import db, User
from routes import bp
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///nextlogic.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# CORS for Netlify frontend
CORS(app, supports_credentials=True, origins=[
    'https://nextlogicai.com',
    'https://www.nextlogicai.com',
    'https://nextlogicai.netlify.app',
    'http://localhost:3000',
    'http://localhost:5000'
])

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'bp.login'  # if you have a login route

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Register blueprints
app.register_blueprint(bp)

# Root route
@app.route('/')
def home():
    return {
        "message": "NextLogicAI Educational Platform API",
        "status": "running",
        "version": "2.0"
    }

# === DATABASE + ADMIN SETUP (RUNS ONCE AT STARTUP) ===
with app.app_context():
    db.create_all()  # Create tables
    print("Database tables ready!")

    # Create default admin if none exists
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(
            name='Admin',
            email='admin@nextlogicai.com',
            role='admin'
        )
        admin.set_password('admin123')  # CHANGE IN PRODUCTION!
        db.session.add(admin)
        db.session.commit()
        print("Default admin created: admin@nextlogicai.com / admin123")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)