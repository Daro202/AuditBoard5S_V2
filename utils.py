import pandas as pd
import os
from app import app

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    """Check if uploaded file has allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_excel_data(file_path):
    """Load machines and questions from Excel file
    
    Expected format:
    - First sheet: machines (column with machine names)
    - Second sheet: questions (columns: code, description)
    """
    try:
        # Read Excel file
        excel_file = pd.ExcelFile(file_path)
        
        if len(excel_file.sheet_names) < 2:
            raise ValueError("Plik Excel musi zawierać co najmniej 2 arkusze (maszyny i pytania)")
        
        # Read machines from first sheet
        machines_df = pd.read_excel(file_path, sheet_name=0)
        machines_data = []
        
        # Try to find machine names in first column
        if not machines_df.empty:
            first_column = machines_df.iloc[:, 0]
            machines_data = [str(name) for name in first_column.dropna() if str(name).strip()]
        
        # Read questions from second sheet
        questions_df = pd.read_excel(file_path, sheet_name=1)
        questions_data = []
        
        if not questions_df.empty and len(questions_df.columns) >= 2:
            # Assume first column is code, second is description
            for _, row in questions_df.iterrows():
                code = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
                description = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
                
                if code and description:
                    questions_data.append({
                        'code': code,
                        'description': description
                    })
        
        app.logger.info(f"Loaded {len(machines_data)} machines and {len(questions_data)} questions")
        return machines_data, questions_data
        
    except Exception as e:
        app.logger.error(f"Error loading Excel data: {str(e)}")
        raise Exception(f"Błąd wczytywania danych z Excela: {str(e)}")

def create_sample_excel():
    """Create a sample Excel file for testing purposes"""
    # Sample machines
    machines = ['MARTIN', 'JUMBO', 'DOMINO', 'HEIDELBERG', 'KOLBUS']
    
    # Sample questions
    questions = [
        {'code': '5S-01', 'description': 'Czy miejsce pracy jest czyste i uporządkowane?'},
        {'code': '5S-02', 'description': 'Czy wszystkie narzędzia są na swoich miejscach?'},
        {'code': '5S-03', 'description': 'Czy na stanowisku nie ma niepotrzebnych przedmiotów?'},
        {'code': '5S-04', 'description': 'Czy instrukcje są widoczne i aktualne?'},
        {'code': '5S-05', 'description': 'Czy maszyna jest czysta i sprawna?'},
    ]
    
    try:
        # Create data directory
        os.makedirs('data', exist_ok=True)
        
        # Create Excel file with two sheets
        with pd.ExcelWriter('data/sample_data.xlsx', engine='openpyxl') as writer:
            # Machines sheet
            machines_df = pd.DataFrame({'Maszyny': machines})
            machines_df.to_excel(writer, sheet_name='Maszyny', index=False)
            
            # Questions sheet
            questions_df = pd.DataFrame(questions)
            questions_df.to_excel(writer, sheet_name='Pytania', index=False)
        
        app.logger.info("Sample Excel file created successfully")
        return True
        
    except Exception as e:
        app.logger.error(f"Error creating sample Excel: {str(e)}")
        return False
