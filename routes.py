import os
import random
from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from app import app, db
from models import Machine, Question, Audit, AuditSession
from utils import load_excel_data, allowed_file
from datetime import datetime

@app.route('/')
def index():
    """Main audit page with random machine-question pair"""
    # Check if we have machines and questions
    machine_count = Machine.query.count()
    question_count = Question.query.count()
    
    if machine_count == 0 or question_count == 0:
        flash('Brak danych w bazie. Proszę zaimportować plik Excel z maszynami i pytaniami.', 'warning')
        return render_template('index.html', no_data=True)
    
    # Get or create a random unused pair
    unused_session = AuditSession.query.filter_by(used=False).first()
    
    if not unused_session:
        # Create new session pairs if none exist
        _create_new_audit_session()
        unused_session = AuditSession.query.filter_by(used=False).first()
    
    if not unused_session:
        flash('Wszystkie pary maszyna-pytanie zostały już wykorzystane.', 'info')
        return render_template('index.html', completed=True)
    
    machine = Machine.query.get(unused_session.machine_id)
    question = Question.query.get(unused_session.question_id)
    
    return render_template('index.html', 
                         machine=machine, 
                         question=question, 
                         session_id=unused_session.id)

@app.route('/submit_audit', methods=['POST'])
def submit_audit():
    """Submit audit result"""
    try:
        session_id = request.form.get('session_id')
        status = request.form.get('status')
        description = request.form.get('description')
        auditor_name = request.form.get('auditor_name', '')
        
        # Validate required fields
        if not all([session_id, status, description]):
            flash('Wszystkie pola są wymagane.', 'error')
            return redirect(url_for('index'))
        
        # Get the session
        session = AuditSession.query.get(session_id)
        if not session or session.used:
            flash('Nieprawidłowa sesja audytu.', 'error')
            return redirect(url_for('index'))
        
        # Handle file upload
        photo_path = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to prevent filename conflicts
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                filename = timestamp + filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                photo_path = f'uploads/{filename}'
        
        # Create audit record
        audit = Audit(
            machine_id=session.machine_id,
            question_id=session.question_id,
            status=status,
            description=description,
            photo_path=photo_path,
            auditor_name=auditor_name
        )
        
        # Mark session as used
        session.used = True
        
        db.session.add(audit)
        db.session.commit()
        
        flash('Audyt został zapisany pomyślnie.', 'success')
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error submitting audit: {str(e)}")
        flash('Wystąpił błąd podczas zapisywania audytu.', 'error')
    
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    """Audit dashboard with grid visualization"""
    machines = Machine.query.all()
    questions = Question.query.all()
    
    # Get all audits with their relationships
    audits = Audit.query.all()
    
    # Create audit matrix
    audit_matrix = {}
    for audit in audits:
        key = f"{audit.machine_id}_{audit.question_id}"
        if key not in audit_matrix:
            audit_matrix[key] = []
        audit_matrix[key].append(audit)
    
    return render_template('dashboard.html', 
                         machines=machines, 
                         questions=questions, 
                         audit_matrix=audit_matrix)

@app.route('/upload_excel', methods=['POST'])
def upload_excel():
    """Upload and process Excel file with machines and questions"""
    try:
        if 'excel_file' not in request.files:
            flash('Nie wybrano pliku.', 'error')
            return redirect(url_for('index'))
        
        file = request.files['excel_file']
        if file.filename == '':
            flash('Nie wybrano pliku.', 'error')
            return redirect(url_for('index'))
        
        if file and file.filename.endswith(('.xlsx', '.xls')):
            # Save temporary file
            filename = secure_filename(file.filename)
            temp_path = os.path.join('data', filename)
            os.makedirs('data', exist_ok=True)
            file.save(temp_path)
            
            # Load data from Excel
            machines_data, questions_data = load_excel_data(temp_path)
            
            # Clear existing data
            AuditSession.query.delete()
            Audit.query.delete()
            Machine.query.delete()
            Question.query.delete()
            
            # Add machines
            for machine_name in machines_data:
                machine = Machine(name=machine_name.strip())
                db.session.add(machine)
            
            # Add questions
            for question_data in questions_data:
                if 'code' in question_data and 'description' in question_data:
                    question = Question(
                        code=question_data['code'].strip(),
                        description=question_data['description'].strip()
                    )
                    db.session.add(question)
            
            db.session.commit()
            
            # Create new audit session
            _create_new_audit_session()
            
            # Clean up temp file
            os.remove(temp_path)
            
            flash(f'Wczytano {len(machines_data)} maszyn i {len(questions_data)} pytań.', 'success')
        else:
            flash('Nieprawidłowy format pliku. Użyj pliku Excel (.xlsx lub .xls).', 'error')
    
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error uploading Excel: {str(e)}")
        flash(f'Wystąpił błąd podczas wczytywania pliku: {str(e)}', 'error')
    
    return redirect(url_for('index'))

@app.route('/reset_session')
def reset_session():
    """Reset audit session to start over"""
    try:
        AuditSession.query.delete()
        _create_new_audit_session()
        flash('Sesja audytu została zresetowana.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error resetting session: {str(e)}")
        flash('Wystąpił błąd podczas resetowania sesji.', 'error')
    
    return redirect(url_for('index'))

def _create_new_audit_session():
    """Create new audit session with all machine-question pairs"""
    machines = Machine.query.all()
    questions = Question.query.all()
    
    # Create all possible combinations
    pairs = []
    for machine in machines:
        for question in questions:
            pairs.append(AuditSession(
                machine_id=machine.id,
                question_id=question.id,
                used=False
            ))
    
    # Shuffle the pairs for random order
    random.shuffle(pairs)
    
    # Add to database
    for pair in pairs:
        db.session.add(pair)
    
    db.session.commit()
    app.logger.info(f"Created {len(pairs)} audit session pairs")

@app.route('/api/audit_data/<int:machine_id>/<int:question_id>')
def get_audit_data(machine_id, question_id):
    """API endpoint to get audit data for tooltip"""
    audits = Audit.query.filter_by(machine_id=machine_id, question_id=question_id).all()
    
    if not audits:
        return jsonify({'status': 'none', 'message': 'Brak audytu'})
    
    # Get the latest audit
    latest_audit = audits[-1]
    
    return jsonify({
        'status': latest_audit.status,
        'description': latest_audit.description,
        'auditor': latest_audit.auditor_name or 'Nieznany',
        'date': latest_audit.created_at.strftime('%Y-%m-%d %H:%M'),
        'photo_path': latest_audit.photo_path
    })
