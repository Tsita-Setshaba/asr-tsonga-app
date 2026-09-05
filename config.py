import os

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://flaskuser:flaskpass123@localhost:5432/flask_db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'super-secret-key')
    PRODUCTION = os.getenv('PRODUCTION', 'false').lower() == 'true'
