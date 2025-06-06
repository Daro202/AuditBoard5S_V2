#!/usr/bin/env python3
"""
Script to create sample Excel data for testing
"""
import pandas as pd
import os

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
        {'code': '5S-06', 'description': 'Czy przestrzegane są zasady bezpieczeństwa?'},
        {'code': '5S-07', 'description': 'Czy oznaczenia są czytelne i kompletne?'},
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
        
        print("Sample Excel file created successfully at data/sample_data.xlsx")
        return True
        
    except Exception as e:
        print(f"Error creating sample Excel: {str(e)}")
        return False

if __name__ == '__main__':
    create_sample_excel()