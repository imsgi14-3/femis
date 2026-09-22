"""Insert a complete test student record for bot testing."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "femis-web" / "instance" / "femis.db"

conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

# Delete incomplete test records
c.execute('DELETE FROM students WHERE name IN ("Test Student", "Ahmed Khan")')

# Insert a complete test record with all required fields
c.execute("""INSERT INTO students (
    name, is_bform_available, b_form, gender, date_of_birth,
    birth_province_id, birth_district_id, nationality, address_type,
    house, street, contact_number, city_id, religion, language_id,
    email, blood_group,
    present_address_type, present_house, present_street, same_address,
    father_name, father_cnic, is_father_alive, father_contact,
    father_profession, father_qualification, father_monthly_income,
    mother_name, is_mother_alive, mother_contact,
    mother_profession, mother_qualification, mother_monthly_income,
    is_orphan, class_id, section_id, date_of_admission, class_admitted_id,
    medium_of_instruction, mode_of_study, admission_number,
    primary_education_completion_years, total_siblings, bus_route,
    emergency_name, emergency_contact, emergency_relation,
    is_refugee, is_registered_refugee,
    difficulty_seeing_board, difficulty_reading_writing,
    difficulty_remembering, difficulty_concentrating
) VALUES (
    "Ahmed Khan", 1, "35202-1234567-1", "Male", "2012-05-15",
    "Punjab", "Lahore", "Pakistani", "Sector",
    "123", "456 Street", "0300-1234567", "Lahore", "Muslim", "Urdu",
    "ahmed@test.com", "B+",
    "Sector", "123", "456 Street", 1,
    "Muhammad Khan", "35202-7654321-1", "Yes", "0321-1234567",
    "Businessman", "Post Graduate", "50,001 - 100,000",
    "Fatima Khan", "Yes", "0333-1234567",
    "Housewife", "Intermediate", "Lessthan 50,000",
    0, "5", "A", "2024-01-15", "5",
    "English", "Day Scholar", "ADM-001",
    "5", 2, "No",
    "Ali Khan", "0345-1234567", "Uncle",
    0, 0,
    "No Difficulty", "No Difficulty",
    "No Difficulty", "No Difficulty"
)""")

conn.commit()
count = c.execute("SELECT COUNT(*) FROM students").fetchone()[0]
print(f"Rows after insert: {count}")

# Verify the record
c.execute("SELECT name, gender, class_id, section_id FROM students WHERE name = 'Ahmed Khan'")
row = c.fetchone()
print(f"Test record: {row}")

conn.close()
print("Done!")
