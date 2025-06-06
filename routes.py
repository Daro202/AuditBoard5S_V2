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
import base64
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

# Register HEIF opener with Pillow
pillow_heif.register_heif_opener()

# Configure Cloudinary with debug logging
cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME')
api_key = os.environ.get('CLOUDINARY_API_KEY')
api_secret = os.environ.get('CLOUDINARY_API_SECRET')

app.logger.info(f"Cloudinary config - Cloud name exists: {bool(cloud_name)}")
app.logger.info(f"Cloudinary config - API key exists: {bool(api_key)}")
app.logger.info(f"Cloudinary config - API secret exists: {bool(api_secret)}")

cloudinary.config(
    cloud_name=cloud_name,
    api_key=api_key,
    api_secret=api_secret,
    secure=True
)

# Global request interceptor to catch all POST requests
@app.before_request
def log_all_requests():
    if request.method == 'POST':
        app.logger.critical(f"POST REQUEST: {request.endpoint} - {request.url}")
        app.logger.critical(f"Form keys: {list(request.form.keys())}")
        app.logger.critical(f"Files keys: {list(request.files.keys())}")
        print(f"=== POST REQUEST INTERCEPTED: {request.endpoint} ===")
        print(f"URL: {request.url}")
        print(f"Form: {list(request.form.keys())}")
        print(f"Files: {list(request.files.keys())}")

def upload_to_cloudinary(file_obj, filename):
    """Upload image to Cloudinary cloud storage with simplified config"""
    try:
        # Reset file pointer to beginning
        file_obj.seek(0)
        
        # Simplified upload without complex transformations
        result = cloudinary.uploader.upload(
            file_obj,
            folder="audit_photos",
            use_filename=True,
            unique_filename=True,
            resource_type="auto"
        )
        
        app.logger.info(f"Successfully uploaded to Cloudinary: {result['secure_url']}")
        return result['secure_url']
        
    except Exception as e:
        app.logger.error(f"Error uploading to Cloudinary: {str(e)}")
        # Fallback: return None and handle gracefully
        return None

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
                        # Create BytesIO object for Cloudinary upload
                        image_buffer = io.BytesIO(image_data)
                        
                        # Upload to Cloudinary
                        cloudinary_url = upload_to_cloudinary(image_buffer, photo_filename)
                        
                        if cloudinary_url:
                            photo_path = cloudinary_url
                            app.logger.info(f"Base64 photo uploaded to Cloudinary: {photo_path}")
                        else:
                            app.logger.error("Failed to upload to Cloudinary")
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
                    
                    # Check for HEIC/HEIF and convert
                    is_heic = (file.filename.lower().endswith('.heic') or 
                             file.filename.lower().endswith('.heif') or
                             (file.content_type and file.content_type in ['image/heic', 'image/heif']))
                    
                    if is_heic:
                        app.logger.info("Converting HEIC/HEIF file")
                        converted_buffer, converted_filename = convert_heic_to_jpeg(file, file.filename)
                        if converted_buffer and converted_filename:
                            file = converted_buffer
                            original_filename = converted_filename
                            app.logger.info(f"Converted to: {converted_filename}")
                        else:
                            original_filename = file.filename
                            app.logger.warning("HEIC conversion failed")
                    else:
                        original_filename = file.filename
                    
                    if allowed_file(original_filename):
                        app.logger.info(f"Uploading regular file to Cloudinary: {original_filename}")
                        
                        # Upload to Cloudinary
                        cloudinary_url = upload_to_cloudinary(file, original_filename)
                        
                        if cloudinary_url:
                            photo_path = cloudinary_url
                            app.logger.info(f"Regular photo uploaded to Cloudinary: {photo_path}")
                        else:
                            app.logger.error("Failed to upload regular file to Cloudinary")
                    else:
                        app.logger.warning(f"File extension not allowed: {original_filename}")
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
                
                # Upload to Cloudinary
                cloudinary_url = upload_to_cloudinary(image_buffer, photo_filename)
                if cloudinary_url:
                    photo_path = cloudinary_url
                    app.logger.info(f"Mobile photo uploaded to Cloudinary: {photo_path}")
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
        
        # Upload to Cloudinary
        cloudinary_url = upload_to_cloudinary(file, file.filename)
        
        if cloudinary_url:
            return jsonify({'success': True, 'url': cloudinary_url})
        else:
            return jsonify({'error': 'Błąd uploadowania'}), 500
            
    except Exception as e:
        app.logger.error(f"Direct upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
