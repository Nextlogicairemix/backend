from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    access_code = db.Column(db.String(50))
    course_completed = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(10), default='student')  # 'student' or 'admin'
    school = db.Column(db.String(100))
    
    # Premium tracking
    is_premium = db.Column(db.Boolean, default=False)
    premium_expires_at = db.Column(db.DateTime)
    
    # For non-school users (guest tracking)
    guest_uses_left = db.Column(db.Integer, default=3)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def is_school_user(self):
        """Check if user is part of a school (has access code)"""
        return self.access_code is not None
    
    def can_use_premium_features(self):
        """Check if user can access premium features"""
        if self.is_premium:
            if self.premium_expires_at and self.premium_expires_at > datetime.utcnow():
                return True
        return False


class AccessCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    school_name = db.Column(db.String(100))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    creator = db.relationship('User', backref='created_codes', foreign_keys=[created_by])


class RemixHistory(db.Model):
    """Track what tools students are using"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tool_type = db.Column(db.String(50))  # 'tweet', 'email', 'blog', etc.
    input_text = db.Column(db.Text)
    output_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='remix_history')


class CourseProgress(db.Model):
    """Track student progress through the 4 course modules"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    module_number = db.Column(db.Integer)  # 1, 2, 3, or 4
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    
    user = db.relationship('User', backref='course_progress')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'module_number', name='unique_user_module'),
    )