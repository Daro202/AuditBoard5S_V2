#!/usr/bin/env python3
"""
Skrypt naprawczy dla uploadowania zdjęć z urządzeń mobilnych
Analizuje i naprawia problemy z zapisywaniem plików
"""

import os
import sys
from pathlib import Path

def check_upload_folder():
    """Sprawdza i tworzy folder uploads"""
    upload_path = Path("static/uploads")
    
    print(f"Sprawdzam folder uploads: {upload_path.absolute()}")
    
    if not upload_path.exists():
        upload_path.mkdir(parents=True, exist_ok=True)
        print("✓ Utworzono folder uploads")
    else:
        print("✓ Folder uploads istnieje")
    
    # Sprawdź uprawnienia
    if os.access(upload_path, os.W_OK):
        print("✓ Folder ma uprawnienia do zapisu")
    else:
        print("✗ Brak uprawnień do zapisu!")
        return False
    
    return True

def check_config():
    """Sprawdza konfigurację aplikacji"""
    try:
        from app import app
        print(f"Upload folder config: {app.config.get('UPLOAD_FOLDER', 'BRAK')}")
        return True
    except Exception as e:
        print(f"Błąd konfiguracji: {e}")
        return False

def analyze_recent_audits():
    """Analizuje ostatnie audyty w bazie danych"""
    try:
        from app import app, db
        from models import Audit
        
        with app.app_context():
            recent_audits = Audit.query.order_by(Audit.created_at.desc()).limit(5).all()
            
            print(f"\nOstatnie {len(recent_audits)} audytów:")
            for audit in recent_audits:
                photo_status = "BRAK ZDJĘCIA"
                if audit.photo_path:
                    file_path = Path(audit.photo_path.replace('uploads/', 'static/uploads/'))
                    if file_path.exists():
                        photo_status = f"PLIK ISTNIEJE ({file_path.stat().st_size} bytes)"
                    else:
                        photo_status = f"PLIK BRAKUJE: {file_path}"
                
                print(f"ID: {audit.id}, Ścieżka: {audit.photo_path}, Status: {photo_status}")
                
    except Exception as e:
        print(f"Błąd analizy audytów: {e}")

def main():
    print("=== NAPRAWA UPLOADOWANIA ZDJĘĆ ===\n")
    
    # Sprawdź folder uploads
    if not check_upload_folder():
        print("Nie można naprawić problemu z folderem uploads")
        return False
    
    # Sprawdź konfigurację
    if not check_config():
        print("Problem z konfiguracją aplikacji")
        return False
    
    # Analizuj ostatnie audyty
    analyze_recent_audits()
    
    print("\n=== ANALIZA ZAKOŃCZONA ===")
    return True

if __name__ == "__main__":
    main()