from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# -------------------------------
# User Model
# -------------------------------
class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(512), nullable=True)  # Nullable for OAuth users
    name = db.Column(db.String(100), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True)
    login_provider = db.Column(db.String(50), default='email')  # email, google, facebook
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    # Password methods
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# -------------------------------
# File Uploads 
# -------------------------------
class FileUpload(db.Model):
    __tablename__ = 'file_upload'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    file_type = db.Column(db.String(20)) 
    transcribed = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref=db.backref('files', lazy=True))


# -------------------------------
# Transcriptions (from file or mic)
# -------------------------------
class Transcription(db.Model):
    __tablename__ = 'transcription'

    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey('file_upload.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    from_recording = db.Column(db.Boolean, default=False)  

    user = db.relationship('User', backref=db.backref('transcriptions', lazy=True))
    file = db.relationship('FileUpload', backref=db.backref('transcription', uselist=False))


# -------------------------------
# Security Settings 
# -------------------------------
class SecuritySettings(db.Model):
    __tablename__ = 'security_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    login_alerts = db.Column(db.Boolean, default=True)
    trusted_devices = db.Column(db.JSON, default=[])
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('security_settings', uselist=False))


# -------------------------------
# User Preferences 
# -------------------------------
class UserPreference(db.Model):
    __tablename__ = 'user_preference'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    dark_mode = db.Column(db.Boolean, default=False)
    language = db.Column(db.String(50), default='en')
    notifications_enabled = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref=db.backref('preferences', uselist=False))


# -------------------------------
# Helper: Auto-create all tables
# -------------------------------
def init_db(app):
    with app.app_context():
        db.init_app(app)
        db.create_all()
