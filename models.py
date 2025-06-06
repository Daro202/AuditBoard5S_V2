from app import db
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean

class Machine(db.Model):
    """Model for machines that can be audited"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to audits
    audits = db.relationship('Audit', backref='machine', lazy=True)
    
    def __repr__(self):
        return f'<Machine {self.name}>'

class Question(db.Model):
    """Model for audit questions"""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to audits
    audits = db.relationship('Audit', backref='question', lazy=True)
    
    def __repr__(self):
        return f'<Question {self.code}: {self.description[:50]}...>'

class Audit(db.Model):
    """Model for audit results"""
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    status = db.Column(db.String(10), nullable=False)  # 'OK' or 'NOK'
    description = db.Column(db.Text, nullable=False)
    photo_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    auditor_name = db.Column(db.String(100), nullable=True)
    action_completed = db.Column(db.Boolean, default=False)  # Czy działanie zostało zakończone pozytywnie
    audit_sequence = db.Column(db.Integer, nullable=True)  # Kolejny numer audytu dla danej maszyny
    
    def __repr__(self):
        return f'<Audit {self.machine.name} - {self.question.code} - {self.status}>'

class AuditSession(db.Model):
    """Model to track audit sessions and prevent repetitions"""
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    used = db.Column(db.Boolean, default=False)
    session_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Composite unique constraint to prevent duplicate pairs
    __table_args__ = (db.UniqueConstraint('machine_id', 'question_id', name='unique_machine_question'),)
    
    def __repr__(self):
        return f'<AuditSession {self.machine_id}-{self.question_id} Used:{self.used}>'
