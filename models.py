from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    level = db.Column(db.String(10))  # INFO, WARNING, ERROR, DEBUG
    module = db.Column(db.String(50))  # 记录日志的模块/组件
    message = db.Column(db.Text)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(200))

class TranslationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    type = db.Column(db.String(20))  # 'text' 或 'image'
    source_text = db.Column(db.Text)
    translated_text = db.Column(db.Text)
    from_lang = db.Column(db.String(10))
    to_lang = db.Column(db.String(10))
    quality_score = db.Column(db.Integer, nullable=True)
    error = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(50)) 