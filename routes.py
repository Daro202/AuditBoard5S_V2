import os
import random
from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from app import app, db
from models import Machine, Question, Audit, AuditSession
from utils import load_excel_data, allowed_file
from datetime import datetime
from PIL import Image
import pillow_heif
import io

# Register HEIF opener with Pillow
pillow_heif.register_heif_opener()

def convert_heic_to_jpeg(file_obj, filename):
    """Convert HEIC/HEIF file to JPEG format"""
    try:
        # Open HEIC file with Pillow
        image = Image.open(file_obj)
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Create new filename with .jpg extension
        base_name = os.path.splitext(filename)[0]
        new_filename = f"{base_name}.jpg"
        
        # Save to bytes buffer
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)
        
        return buffer, new_filename
    except Exception as e:
        app.logger.error(f"Error converting HEIC to JPEG: {str(e)}")
        return None, None

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
        # Immediate debug logging
        print(f"=== SUBMIT_AUDIT DEBUG ===")
        print(f"Request method: {request.method}")
        print(f"Request files: {list(request.files.keys())}")
        print(f"Request form: {dict(request.form)}")
        print(f"Content type: {request.content_type}")
        
        # Also log to file for persistence
        with open('/tmp/submit_debug.log', 'a') as f:
            f.write(f"\n=== SUBMIT_AUDIT {datetime.now()} ===\n")
            f.write(f"Request method: {request.method}\n")
            f.write(f"Request files: {list(request.files.keys())}\n")
            f.write(f"Request form: {dict(request.form)}\n")
            f.write(f"Content type: {request.content_type}\n")
            f.write(f"Content length: {request.content_length}\n")
        session_id = request.form.get('session_id')
        status = request.form.get('status')
        description = request.form.get('description')
        auditor_name = request.form.get('auditor_name', '')
        action_completed = request.form.get('action_completed') == 'on'
        
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
        
        # Force flush debug logs immediately
        app.logger.info(f"Processing upload - files: {list(request.files.keys())}")
        
        # Check if we have ANY file at all
        if 'photo' not in request.files:
            app.logger.warning("No 'photo' field in request.files")
        else:
            file = request.files['photo']
            if not file or not file.filename:
                app.logger.warning(f"Empty file or no filename: {file}")
            else:
                app.logger.info(f"File received: {file.filename}, size: {file.content_length}")
        
        try:
            # Debug logging to file
            with open('/tmp/upload_debug.log', 'a') as debug_file:
                debug_file.write(f"\n=== Upload Debug {datetime.now()} ===\n")
                debug_file.write(f"Request files: {list(request.files.keys())}\n")
                debug_file.write(f"Request form: {dict(request.form)}\n")
                
                if 'photo' in request.files:
                    file = request.files['photo']
                    debug_file.write(f"File object: {file}\n")
                    debug_file.write(f"Filename: {file.filename}\n")
                    debug_file.write(f"Content type: {file.content_type if file else 'None'}\n")
                    debug_file.write(f"Content length: {file.content_length if file else 'None'}\n")
                    
                    if file and file.filename and file.filename != '':
                        debug_file.write(f"Original filename: {file.filename}\n")
                        
                        # Check if it's HEIC/HEIF format and convert to JPEG
                        is_heic = (file.filename.lower().endswith('.heic') or 
                                 file.filename.lower().endswith('.heif') or
                                 file.content_type in ['image/heic', 'image/heif'])
                        
                        if is_heic:
                            debug_file.write("HEIC/HEIF format detected - converting to JPEG\n")
                            converted_buffer, converted_filename = convert_heic_to_jpeg(file, file.filename)
                            if converted_buffer and converted_filename:
                                file = converted_buffer
                                original_filename = converted_filename
                                debug_file.write(f"Converted to: {converted_filename}\n")
                            else:
                                debug_file.write("HEIC conversion failed\n")
                                original_filename = file.filename
                        else:
                            original_filename = file.filename
                        
                        if allowed_file(original_filename):
                            filename = secure_filename(original_filename)
                            # Add timestamp to prevent filename conflicts
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                            filename = timestamp + filename
                            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                            
                            # Ensure upload directory exists
                            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                            debug_file.write(f"Saving file to: {file_path}\n")
                            debug_file.write(f"Upload folder exists: {os.path.exists(app.config['UPLOAD_FOLDER'])}\n")
                            
                            # Check file content before saving
                            if hasattr(file, 'seek'):
                                file.seek(0, 2)  # Seek to end
                                file_size_before = file.tell()
                                file.seek(0)  # Seek back to beginning
                            else:
                                file_size_before = len(file.read()) if hasattr(file, 'read') else 0
                                if hasattr(file, 'seek'):
                                    file.seek(0)
                            
                            debug_file.write(f"File size before save: {file_size_before} bytes\n")
                            
                            # Save file (handle both file objects and BytesIO)
                            if hasattr(file, 'save'):
                                file.save(file_path)
                            else:
                                with open(file_path, 'wb') as f:
                                    f.write(file.read())
                            debug_file.write(f"File.save() completed\n")
                            
                            # Verify file was saved
                            if os.path.exists(file_path):
                                file_size = os.path.getsize(file_path)
                                photo_path = f'uploads/{filename}'
                                debug_file.write(f"Photo saved successfully: {photo_path}, size: {file_size} bytes\n")
                                app.logger.info(f"Photo saved successfully: {photo_path}, size: {file_size} bytes")
                            else:
                                debug_file.write(f"ERROR: File was not saved to {file_path}\n")
                                app.logger.error(f"File was not saved to {file_path}")
                                photo_path = None  # Don't save path to DB if file doesn't exist
                        else:
                            debug_file.write(f"File extension not allowed: {file.filename}\n")
                            app.logger.warning(f"File extension not allowed: {file.filename}")
                    else:
                        debug_file.write(f"No valid photo file: file={file}, filename={file.filename if file else 'None'}\n")
                        app.logger.info(f"No valid photo file: file={file}, filename={file.filename if file else 'None'}")
                else:
                    debug_file.write("No 'photo' key in request.files\n")
                    app.logger.info("No 'photo' key in request.files")
                    
        except Exception as e:
            with open('/tmp/upload_debug.log', 'a') as debug_file:
                debug_file.write(f"EXCEPTION: {str(e)}\n")
                import traceback
                debug_file.write(f"Traceback: {traceback.format_exc()}\n")
            app.logger.error(f"Error saving photo: {str(e)}")
            # Continue without photo - don't break the audit submission
        
        # Calculate audit sequence number for this machine
        machine_audit_count = Audit.query.filter_by(machine_id=session.machine_id).count()
        audit_sequence = machine_audit_count + 1
        
        # Create audit record
        audit = Audit(
            machine_id=session.machine_id,
            question_id=session.question_id,
            status=status,
            description=description,
            photo_path=photo_path,
            auditor_name=auditor_name,
            action_completed=action_completed,
            audit_sequence=audit_sequence
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
    """Audit dashboard with grid visualization - columns represent audit sequence (1-5)"""
    machines = Machine.query.all()
    
    # Get audits organized by machine and sequence
    audit_matrix = {}
    stats = {}
    
    for machine in machines:
        # Get audits for this machine ordered by sequence
        machine_audits = Audit.query.filter_by(machine_id=machine.id).order_by(Audit.audit_sequence).all()
        
        # Organize audits by sequence (1-5)
        audit_matrix[machine.id] = {}
        for i in range(1, 6):  # Columns 1-5
            audit_matrix[machine.id][i] = None
        
        # Fill in actual audits
        for audit in machine_audits:
            if audit.audit_sequence and audit.audit_sequence <= 5:
                audit_matrix[machine.id][audit.audit_sequence] = audit
        
        # Calculate statistics for this machine
        ok_count = len([a for a in machine_audits if a.status == 'OK'])
        nok_count = len([a for a in machine_audits if a.status == 'NOK'])
        action_completed_count = len([a for a in machine_audits if a.dzialanie_ok])
        
        stats[machine.id] = {
            'ok_count': ok_count,
            'nok_count': nok_count,
            'action_completed_count': action_completed_count,
            'total_audits': len(machine_audits)
        }
    
    return render_template('dashboard.html', 
                         machines=machines, 
                         audit_matrix=audit_matrix,
                         stats=stats)

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

@app.route('/api/audit_data/<int:machine_id>/<int:audit_sequence>')
def get_audit_data(machine_id, audit_sequence):
    """API endpoint to get audit data for tooltip"""
    audit = Audit.query.filter_by(machine_id=machine_id, audit_sequence=audit_sequence).first()
    
    if not audit:
        return jsonify({'status': 'none', 'message': 'Brak audytu'})
    
    # Get question details
    question = Question.query.get(audit.question_id)
    
    return jsonify({
        'status': audit.status,
        'description': audit.description,
        'auditor': audit.auditor_name or 'Nieznany',
        'date': audit.created_at.strftime('%Y-%m-%d %H:%M'),
        'photo_path': audit.photo_path,
        'action_completed': audit.action_completed,
        'question_code': question.code if question else 'N/A',
        'question_description': question.description if question else 'N/A',
        'audit_id': audit.id,
        'opis_dzialania': audit.opis_dzialania,
        'zdjecie_dzialania': audit.zdjecie_dzialania,
        'dzialanie_ok': audit.dzialanie_ok,
        'data_dzialania': audit.data_dzialania.strftime('%Y-%m-%d %H:%M') if audit.data_dzialania else None
    })

@app.route('/save_action', methods=['POST'])
def save_action():
    """Zapisz działanie naprawcze dla audytu"""
    try:
        audit_id = request.form.get('audit_id')
        opis_dzialania = request.form.get('opis_dzialania')
        dzialanie_ok = request.form.get('dzialanie_ok') == 'on'
        
        # Validate required fields
        if not all([audit_id, opis_dzialania]):
            return jsonify({'success': False, 'message': 'Wszystkie pola są wymagane.'})
        
        # Get the audit
        audit = Audit.query.get(audit_id)
        if not audit:
            return jsonify({'success': False, 'message': 'Nieprawidłowy audyt.'})
        
        # Handle file upload for action photo
        zdjecie_dzialania = None
        try:
            if 'zdjecie_dzialania' in request.files:
                file = request.files['zdjecie_dzialania']
                if file and file.filename and file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Add timestamp to prevent filename conflicts
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = f"action_{timestamp}_{filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    # Ensure upload directory exists
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    
                    # Save file
                    file.save(file_path)
                    zdjecie_dzialania = f'uploads/{filename}'
                    app.logger.info(f"Action photo saved successfully: {zdjecie_dzialania}")
                else:
                    app.logger.info("No valid action photo file provided")
        except Exception as e:
            app.logger.error(f"Error saving action photo: {str(e)}")
            # Continue without photo - don't break the action submission
        
        # Update audit record with action details
        audit.opis_dzialania = opis_dzialania
        audit.zdjecie_dzialania = zdjecie_dzialania
        audit.dzialanie_ok = dzialanie_ok
        audit.data_dzialania = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Działanie naprawcze zostało zapisane pomyślnie.',
            'data_dzialania': audit.data_dzialania.strftime('%Y-%m-%d %H:%M'),
            'dzialanie_ok': dzialanie_ok
        })
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error saving action: {str(e)}")
        return jsonify({'success': False, 'message': 'Wystąpił błąd podczas zapisywania działania.'})

@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            return app.send_static_file(f'uploads/{filename}')
        else:
            app.logger.error(f"File not found: {file_path}")
            return "File not found", 404
    except Exception as e:
        app.logger.error(f"Error serving file {filename}: {str(e)}")
        return "File not found", 404

@app.route('/debug_upload', methods=['POST'])
def debug_upload():
    """Debug endpoint for file upload information"""
    try:
        data = request.get_json()
        with open('/tmp/js_upload_debug.log', 'a') as f:
            f.write(f"\n=== JS File Debug {datetime.now()} ===\n")
            f.write(f"Filename: {data.get('filename')}\n")
            f.write(f"Size: {data.get('size')} bytes\n")
            f.write(f"Type: {data.get('type')}\n")
        return {'status': 'logged'}
    except Exception as e:
        return {'error': str(e)}
