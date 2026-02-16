"""
Create a sample Excel file for testing the Import from Excel feature.
Run from Backend directory: python scripts/create_sample_import_excel.py
Output: Backend/sample_students_import.xlsx
"""
import os

try:
    import openpyxl
except ImportError:
    print("Installing openpyxl...")
    os.system("pip install openpyxl")
    import openpyxl

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Students"

# Headers (must match what the import expects)
headers = ["user_id", "name", "email", "major", "year", "semester", "status", "total_credits", "section"]
ws.append(headers)

# Sample rows - use unique IDs that don't conflict with existing students
sample_students = [
    ("TNT-9001", "Emma Wilson", "emma.wilson@uni.edu", "CS", 1, 1, "Active", 0, "A"),
    ("TNT-9002", "Liam Brown", "liam.brown@uni.edu", "CS", 1, 1, "Active", 0, "B"),
    ("TNT-9003", "Olivia Davis", "olivia.davis@uni.edu", "CS", 2, 1, "Active", 30, "A"),
    ("TNT-9004", "Noah Miller", "noah.miller@uni.edu", "CT", 3, 2, "Active", 60, ""),  # No section for year 3+
    ("TNT-9005", "Ava Garcia", "ava.garcia@uni.edu", "SE", 4, 1, "Active", 90, ""),
]

for row in sample_students:
    ws.append(row)

# Save
out_path = os.path.join(os.path.dirname(__file__), "..", "sample_students_import.xlsx")
wb.save(out_path)
print(f"Created: {os.path.abspath(out_path)}")
print("You can use this file to test Import from Excel on the Admin Students page.")
