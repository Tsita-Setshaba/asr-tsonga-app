from flask import Flask, request, jsonify, render_template, session, url_for, redirect, abort
from models import db, User
from config import Config
from asr import ASR
from authlib.integrations.flask_client import OAuth
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_talisman import Talisman
import os, secrets

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)

is_production = app.config['PRODUCTION']

# Session cookie security
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_urlsafe(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=is_production
)

db.init_app(app)

csrf = CSRFProtect(app)

limiter = Limiter(key_func=get_remote_address)
limiter.init_app(app)


csp = {
    'default-src': ["'self'"],
    'script-src': [
        "'self'", "'unsafe-inline'",
        "https://cdnjs.cloudflare.com",
        "https://kit.fontawesome.com"
    ],
    'style-src': [
        "'self'", "'unsafe-inline'",
        "https://cdnjs.cloudflare.com",
        "https://fonts.googleapis.com",
        "https://kit-free.fontawesome.com"
    ],
    'font-src': [
        "'self'",
        "https://fonts.gstatic.com",
        "https://use.fontawesome.com",
        "https://cdnjs.cloudflare.com"
    ],
    'img-src': ["'self'", "data:", "https:"],
}

Talisman(app, content_security_policy=csp)


oauth = OAuth(app)

# Google OAuth
CONF_URL = 'https://accounts.google.com/.well-known/openid-configuration'
oauth.register(
    name='google',
    server_metadata_url=CONF_URL,
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    client_kwargs={'scope': 'openid email profile'}
)

# Facebook OAuth
oauth.register(
    name='facebook',
    client_id=os.getenv('FACEBOOK_CLIENT_ID'),
    client_secret=os.getenv('FACEBOOK_CLIENT_SECRET'),
    access_token_url='https://graph.facebook.com/v11.0/oauth/access_token',
    authorize_url='https://www.facebook.com/v11.0/dialog/oauth',
    api_base_url='https://graph.facebook.com/v11.0/',
    client_kwargs={'scope': 'email'}
)

# Load the ASR model once at startup (pulls from Hugging Face Hub:
# Tsita-Mogau/ASR-Tsonga). This can take a while on first boot while
# it downloads weights - that's expected.
asr_instance = ASR()


@app.before_request
def create_tables():
    db.create_all()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login/google')
def login_google():
    nonce = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    redirect_uri = url_for('authorize_google', _external=True, _scheme='https' if is_production else 'http')
    return oauth.google.authorize_redirect(redirect_uri, nonce=nonce)

@app.route('/authorize/google')
def authorize_google():
    token = oauth.google.authorize_access_token()
    nonce = session.pop('nonce', None)
    if not nonce:
        abort(400, "Missing nonce in session")

    user_info = oauth.google.parse_id_token(token, nonce=nonce)
    if not user_info or not user_info.get('email_verified'):
        abort(400, "Invalid Google token or email not verified")

    user = User.query.filter_by(email=user_info['email']).first()
    if not user:
        user = User(email=user_info['email'], name=user_info.get('name'))
        db.session.add(user)
        db.session.commit()

    session['user'] = {
        'id': user_info.get('sub'),
        'name': user_info.get('name'),
        'email': user_info.get('email'),
        'picture': user_info.get('picture'),
    }
    return redirect('/dashboard')

@app.route('/login/facebook')
def login_facebook():
    redirect_uri = url_for('authorize_facebook', _external=True, _scheme='https' if is_production else 'http')
    return oauth.facebook.authorize_redirect(redirect_uri)

@app.route('/authorize/facebook')
def authorize_facebook():
    token = oauth.facebook.authorize_access_token()
    resp = oauth.facebook.get('me?fields=id,name,email')
    user_data = resp.json()
    if 'email' not in user_data:
        abort(400, "Facebook account email not available")

    user = User.query.filter_by(email=user_data['email']).first()
    if not user:
        user = User(email=user_data['email'], name=user_data.get('name'))
        db.session.add(user)
        db.session.commit()

    session['user'] = {
        'id': user_data.get('id'),
        'name': user_data.get('name'),
        'email': user_data.get('email'),
        'picture': None
    }
    return redirect('/dashboard')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.errorhandler(404)
def page_not_found(e):
    return render_template('notFound.html'), 404

def login_required(view_func):
    from functools import wraps
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login_page'))
        return view_func(*args, **kwargs)
    return wrapped_view

@app.route('/dashboard')
@login_required
def dashboard():
    user = session.get('user')
    return render_template('dashboard.html', user=user, current_page='home')

@app.route('/settings')
@login_required
def settings_page():
    user = session.get('user')
    return render_template('settings.html', user=user, current_page='settings')

@app.route('/myfiles')
@login_required
def myFiles_page():
    user = session.get('user')
    # TODO: replace with a real query, e.g.
    # files = FileUpload.query.filter_by(user_id=user['id']).all()
    files = []
    return render_template('myFiles.html', user=user, current_page='myfiles', files=files)

@app.route('/transcribe')
@login_required
def transcribe_page():
    user = session.get('user')
    return render_template('transcribe.html', user=user, current_page='transcribe')

@app.route('/transcribe/upload', methods=['POST'])
@csrf.exempt
@login_required
def transcribe_upload():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    if audio_file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    try:
        audio_bytes = audio_file.read()
        text = asr_instance.transcribe(audio_bytes)
        return jsonify({'text': text}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/login', methods=['GET'])
def login_page():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@limiter.limit("5 per minute")
@app.route('/login', methods=['POST'])
@csrf.exempt 
def login_user():
    if not request.is_json:
        return jsonify({'error': 'Invalid request'}), 400

    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        session.clear()
        session['user'] = {
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'picture': user.picture if hasattr(user, 'picture') else None,
        }
        return jsonify({'message': 'Login successful'}), 200

    return jsonify({'error': 'Invalid credentials'}), 401

@limiter.limit("3 per minute")
@app.route('/register', methods=['GET'])
def register_page():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@limiter.limit("3 per minute")
@app.route('/register', methods=['POST'])
@csrf.exempt
def register_user():
    if not request.is_json:
        return jsonify({'error': 'Invalid request'}), 400

    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already exists'}), 409

    new_user = User(email=email)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({'message': 'Registered successfully'}), 201

if __name__ == '__main__':
    print(f"Running in {'PRODUCTION' if is_production else 'DEVELOPMENT'} mode using {'HTTPS' if is_production else 'HTTP'}")
    app.run(debug=not is_production, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
