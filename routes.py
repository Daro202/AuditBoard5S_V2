import os
import random
from flask import render_template, request, redirect, url_for, flash, jsonify, send_file
from werkzeug.utils import secure_filename
from app import app, db
from models import Machine, Question, Audit, AuditSession
from utils import load_excel_data, allowed_file
from datetime import datetime
from openpyxl import Workbook
from PIL import Image
import pillow_heif
import io
import base64
import pytz

pillow_heif.register_heif_opener()

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'heic', 'heif'}

def upload_photo_local(file_obj, filename=None):
    """
    Upload photo to local storage: static/uploads/audit_photos/
    
    Args:
        file_obj: FileStorage from request.files["photo"] OR BytesIO object
        filename: Optional filename (required if file_obj is BytesIO)
    
    Returns:
        str: Relative path like 'uploads/audit_photos/20251125_101530_maszyna1.jpg'
        None: If upload fails
    """
    if not file_obj:
        app.logger.error("No file provided")
        return None
    
    if hasattr(file_obj, 'filename') and file_obj.filename:
        filename = file_obj.filename
    
    if not filename:
        app.logger.error("No filename provided")
        return None
    
    file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    if file_ext not in ALLOWED_EXTENSIONS:
        app.logger.error(f"Invalid file extension: {file_ext}")
        return None
    
    try:
        poland_tz = pytz.timezone('Europe/Warsaw')
        timestamp = datetime.now(poland_tz).strftime('%Y%m%d_%H%M%S')
        
        upload_subdir = os.path.join(app.config['UPLOAD_FOLDER'], 'audit_photos')
        os.makedirs(upload_subdir, exist_ok=True)
        
        if file_ext in ['heic', 'heif']:
            app.logger.info(f"Converting HEIC/HEIF to JPEG: {filename}")
            image = Image.open(file_obj)
            
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            base_name = os.path.splitext(secure_filename(filename))[0]
            final_filename = f"{timestamp}_{base_name}.jpg"
            file_path = os.path.join(upload_subdir, final_filename)
            image.save(file_path, format='JPEG', quality=85)
            
            relative_path = f"uploads/audit_photos/{final_filename}"
            app.logger.info(f"HEIC converted and saved: {relative_path}")
            return relative_path
            
        else:
            secure_name = secure_filename(filename)
            final_filename = f"{timestamp}_{secure_name}"
            file_path = os.path.join(upload_subdir, final_filename)
            
            if hasattr(file_obj, 'save'):
                file_obj.save(file_path)
            else:
                if hasattr(file_obj, 'seek'):
                    file_obj.seek(0)
                with open(file_path, 'wb') as f:
                    if hasattr(file_obj, 'read'):
                        f.write(file_obj.read())
                    else:
                        f.write(file_obj)
            
            relative_path = f"uploads/audit_photos/{final_filename}"
            app.logger.info(f"Photo saved locally: {relative_path}")
            return relative_path
            
    except Exception as e:
        app.logger.error(f"Failed to upload photo: {str(e)}")
        return None

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
    # Force immediate logging to identify if endpoint is called
    print("=== SUBMIT_AUDIT ENDPOINT CALLED ===")
    app.logger.critical("=== SUBMIT_AUDIT ENDPOINT CALLED ===")
    
    try:
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
        
        # Handle file upload with Cloudinary
        photo_path = None
        
        try:
            # Debug logging
            app.logger.info(f"=== CLOUDINARY UPLOAD DEBUG ===")
            app.logger.info(f"Form keys: {list(request.form.keys())}")
            app.logger.info(f"Files keys: {list(request.files.keys())}")
            
            # Check for Base64 data first (mobile devices)
            photo_base64 = request.form.get('photo_base64')
            photo_filename = request.form.get('photo_filename')
            
            app.logger.info(f"Base64 data present: {bool(photo_base64)}")
            app.logger.info(f"Base64 filename: {photo_filename}")
            
            if photo_base64 and photo_filename:
                # Process Base64 upload to Cloudinary
                app.logger.info("Processing Base64 upload to Cloudinary")
                try:
                    # Decode Base64 data
                    if ',' in photo_base64:
                        header, data = photo_base64.split(',', 1)
                    else:
                        data = photo_base64
                    
                    image_data = base64.b64decode(data)
                    app.logger.info(f"Decoded image size: {len(image_data)} bytes")
                    
                    if allowed_file(photo_filename):
                        # Create BytesIO object for upload
                        image_buffer = io.BytesIO(image_data)
                        
                        # Upload to local storage
                        photo_path = upload_photo_local(image_buffer, photo_filename)
                        
                        if photo_path:
                            app.logger.info(f"Base64 photo uploaded locally: {photo_path}")
                        else:
                            app.logger.error("Failed to upload Base64 photo")
                    else:
                        app.logger.warning(f"File extension not allowed: {photo_filename}")
                
                except Exception as e:
                    app.logger.error(f"Base64 processing error: {str(e)}")
                    import traceback
                    app.logger.error(f"Traceback: {traceback.format_exc()}")
            
            elif 'photo' in request.files:
                # Process regular file upload
                file = request.files['photo']
                app.logger.info(f"Processing regular file upload: {file.filename if file else 'None'}")
                
                if file and file.filename and file.filename != '':
                    app.logger.info(f"File details: name={file.filename}, type={file.content_type}")
                    
                    # Upload to local storage (HEIC conversion handled automatically)
                    photo_path = upload_photo_local(file)
                    
                    if photo_path:
                        app.logger.info(f"Photo uploaded locally: {photo_path}")
                    else:
                        app.logger.error("Failed to upload file")
                else:
                    app.logger.info("No valid file found")
            else:
                app.logger.info("No photo data found in request")
                            
        except Exception as e:
            app.logger.error(f"Error saving photo: {str(e)}")
            import traceback
            app.logger.error(f"Traceback: {traceback.format_exc()}")
            # Continue without photo - don't break the audit submission
        
        # Calculate audit sequence number for this machine
        machine_audit_count = Audit.query.filter_by(machine_id=session.machine_id).count()
        audit_sequence = machine_audit_count + 1
        
        # Create audit record
        audit = Audit()
        audit.machine_id = session.machine_id
        audit.question_id = session.question_id
        audit.status = status
        audit.description = description
        audit.photo_path = photo_path
        audit.auditor_name = auditor_name
        audit.action_completed = action_completed
        audit.audit_sequence = audit_sequence
        
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

@app.route('/export_excel')
def export_excel():
    """Export machines and questions to Excel file"""
    try:
        wb = Workbook()
        
        ws_machines = wb.active
        ws_machines.title = "Maszyny"
        ws_machines.append(["Nazwa maszyny"])
        
        machines = Machine.query.order_by(Machine.id).all()
        for machine in machines:
            ws_machines.append([machine.name])
        
        ws_questions = wb.create_sheet("Pytania")
        ws_questions.append(["Kod", "Opis"])
        
        questions = Question.query.order_by(Question.id).all()
        for question in questions:
            ws_questions.append([question.code, question.description])
        
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='maszyny_pytania.xlsx'
        )
        
    except Exception as e:
        app.logger.error(f"Error exporting Excel: {str(e)}")
        flash('Wystąpił błąd podczas eksportu.', 'error')
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

@app.route('/delete_all_audits', methods=['POST'])
def delete_all_audits():
    """Delete all audits after password verification"""
    admin_password = request.form.get('admin_password', '')
    correct_password = os.environ.get('ADMIN_PASSWORD', '4321')
    
    if admin_password != correct_password:
        flash('Nieprawidłowe hasło.', 'error')
        return redirect(url_for('index'))
    
    try:
        # Delete all audit photos from disk
        audits = Audit.query.all()
        for audit in audits:
            if audit.photo_path:
                photo_full_path = os.path.join('static', audit.photo_path)
                if os.path.exists(photo_full_path):
                    try:
                        os.remove(photo_full_path)
                        app.logger.info(f"Deleted photo: {photo_full_path}")
                    except Exception as e:
                        app.logger.error(f"Error deleting photo {photo_full_path}: {e}")
        
        # Delete all audits from database
        deleted_count = Audit.query.delete()
        
        # Reset sessions
        AuditSession.query.delete()
        _create_new_audit_session()
        
        db.session.commit()
        flash(f'Usunięto {deleted_count} audytów i zresetowano sesję.', 'success')
        app.logger.info(f"Deleted {deleted_count} audits and reset session")
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting audits: {str(e)}")
        flash('Wystąpił błąd podczas usuwania audytów.', 'error')
    
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

@app.route('/submit_audit_mobile', methods=['POST'])
def submit_audit_mobile():
    """Mobile-specific audit submission without file upload issues"""
    app.logger.critical("=== MOBILE AUDIT ENDPOINT CALLED ===")
    print("=== MOBILE AUDIT ENDPOINT CALLED ===")
    
    try:
        session_id = request.form.get('session_id')
        status = request.form.get('status')
        description = request.form.get('description')
        auditor_name = request.form.get('auditor_name', '')
        action_completed = request.form.get('action_completed') == 'on'
        
        if not all([session_id, status, description]):
            return jsonify({'error': 'Wszystkie pola są wymagane.'}), 400
        
        session = AuditSession.query.get(session_id)
        if not session or session.used:
            return jsonify({'error': 'Nieprawidłowa sesja audytu.'}), 400
        
        machine_audit_count = Audit.query.filter_by(machine_id=session.machine_id).count()
        audit_sequence = machine_audit_count + 1
        
        # Handle photo upload to Cloudinary
        photo_path = None
        photo_base64 = request.form.get('photo_base64')
        photo_filename = request.form.get('photo_filename')
        
        if photo_base64 and photo_filename:
            try:
                # Decode Base64 data
                if ',' in photo_base64:
                    header, data = photo_base64.split(',', 1)
                else:
                    data = photo_base64
                
                image_data = base64.b64decode(data)
                image_buffer = io.BytesIO(image_data)
                
                # Upload to local storage
                photo_path = upload_photo_local(image_buffer, photo_filename)
                if photo_path:
                    app.logger.info(f"Mobile photo uploaded locally: {photo_path}")
            except Exception as e:
                app.logger.error(f"Mobile photo upload error: {str(e)}")
        
        audit = Audit()
        audit.machine_id = session.machine_id
        audit.question_id = session.question_id
        audit.status = status
        audit.description = description
        audit.photo_path = photo_path
        audit.auditor_name = auditor_name
        audit.action_completed = action_completed
        audit.audit_sequence = audit_sequence
        
        session.used = True
        
        db.session.add(audit)
        db.session.commit()
        
        app.logger.info(f"Mobile audit saved: ID {audit.id}")
        return jsonify({'success': True, 'message': 'Audyt zapisany pomyślnie.', 'photo_url': photo_path})
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Mobile audit error: {str(e)}")
        return jsonify({'error': 'Błąd podczas zapisywania.'}), 500

@app.route('/upload_cloudinary', methods=['POST'])
def upload_cloudinary():
    """Direct photo upload to Cloudinary"""
    try:
        if 'photo' not in request.files:
            return jsonify({'error': 'Brak pliku'}), 400
        
        file = request.files['photo']
        if file.filename == '':
            return jsonify({'error': 'Nie wybrano pliku'}), 400
        
        # Upload to local storage
        photo_url = upload_photo_local(file)
        
        if photo_url:
            return jsonify({'success': True, 'url': photo_url, 'method': 'local storage'})
        else:
            return jsonify({'error': 'Błąd zapisywania pliku'}), 500
            
    except Exception as e:
        app.logger.error(f"Direct upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            from flask import send_from_directory
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
        else:
            app.logger.error(f"File not found: static/uploads/{filename}")
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
