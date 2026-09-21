"""FEMIS Web — Student Data Collection Form
Flask app replicating the FEMIS portal's 7-tab student form.
Parents/teachers fill this; the bot reads from the DB and fills the real portal.
"""
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config["SECRET_KEY"] = "femis-web-dev-key-change-in-prod"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///femis.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["TEMPLATES_AUTO_RELOAD"] = True

db = SQLAlchemy(app)

OPTIONS_PATH = Path(__file__).parent / "portal_options.json"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted = db.Column(db.Boolean, default=False)
    locked = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(20), default="student")
    parent_name = db.Column(db.String(200))
    roll_no = db.Column(db.String(20))

    # Tab 1 — Personal Details
    name = db.Column(db.String(200))
    is_bform_available = db.Column(db.String(10))
    b_form = db.Column(db.String(30))
    gender = db.Column(db.String(20))
    date_of_birth = db.Column(db.String(20))
    birth_province_id = db.Column(db.String(100))
    birth_district_id = db.Column(db.String(100))
    nationality = db.Column(db.String(50))
    nationality_id = db.Column(db.String(100))
    domicile_province_id = db.Column(db.String(100))
    domicile_district_id = db.Column(db.String(100))
    address_type = db.Column(db.String(50))
    sector_id = db.Column(db.String(50))
    village_id = db.Column(db.String(100))
    housing_society_id = db.Column(db.String(100))
    house = db.Column(db.String(50))
    street = db.Column(db.String(50))
    contact_number = db.Column(db.String(20))
    city_id = db.Column(db.String(100))
    same_address = db.Column(db.String(10))
    present_house = db.Column(db.String(50))
    present_street = db.Column(db.String(50))
    present_address_type = db.Column(db.String(50))
    present_sector_id = db.Column(db.String(50))
    present_village_id = db.Column(db.String(100))
    present_housing_society_id = db.Column(db.String(100))
    religion = db.Column(db.String(50))
    religion_id = db.Column(db.String(50))
    language_id = db.Column(db.String(50))
    blood_group = db.Column(db.String(10))
    email = db.Column(db.String(100))
    mother_language_other = db.Column(db.String(100))
    present_address_other = db.Column(db.String(500))

    # Tab 2 — Parents / Guardian
    father_name = db.Column(db.String(200))
    father_cnic = db.Column(db.String(20))
    is_father_alive = db.Column(db.String(10))
    father_contact = db.Column(db.String(20))
    father_landline = db.Column(db.String(20))
    father_email = db.Column(db.String(100))
    father_qualification = db.Column(db.String(50))
    father_profession = db.Column(db.String(50))
    father_monthly_income = db.Column(db.String(50))
    father_bps = db.Column(db.String(10))
    father_domicile_province_id = db.Column(db.String(100))
    father_domicile_district_id = db.Column(db.String(100))
    father_profession_other = db.Column(db.String(100))
    mother_name = db.Column(db.String(200))
    is_mother_alive = db.Column(db.String(10))
    mother_cnic = db.Column(db.String(20))
    mother_contact = db.Column(db.String(20))
    mother_landline = db.Column(db.String(20))
    mother_email = db.Column(db.String(100))
    mother_qualification = db.Column(db.String(50))
    mother_profession = db.Column(db.String(50))
    mother_monthly_income = db.Column(db.String(50))
    mother_bps = db.Column(db.String(10))
    mother_profession_other = db.Column(db.String(100))
    is_orphan = db.Column(db.String(10))
    orphan_type = db.Column(db.String(50))
    guardian_name = db.Column(db.String(200))
    guardian_cnic = db.Column(db.String(20))
    guardian_relation = db.Column(db.String(50))
    guardian_contact = db.Column(db.String(20))
    guardian_qualification = db.Column(db.String(50))
    guardian_profession = db.Column(db.String(50))
    guardian_income = db.Column(db.String(50))
    guardian_bps = db.Column(db.String(10))
    guardian_profession_other = db.Column(db.String(100))
    guardian_relation_other = db.Column(db.String(100))

    # Tab 3 — Educational Details
    class_id = db.Column(db.String(50))
    section_id = db.Column(db.String(20))
    class_group_id = db.Column(db.String(50))
    last_class_result = db.Column(db.String(50))
    date_of_admission = db.Column(db.String(20))
    admission_number = db.Column(db.String(50))
    last_fde_institution_id = db.Column(db.String(200))
    class_admitted_id = db.Column(db.String(50))
    last_institution_other = db.Column(db.String(200))
    shift = db.Column(db.String(20))
    medium_of_instruction = db.Column(db.String(20))
    years_primary = db.Column(db.String(10))
    primary_education_completion_years = db.Column(db.String(10))
    school_meal_program_availing = db.Column(db.String(10))
    mode_of_study = db.Column(db.String(20))
    is_hafiz = db.Column(db.String(10))
    girls_stipend = db.Column(db.String(10))
    total_siblings = db.Column(db.String(10))
    siblings_other_fde = db.Column(db.String(10))
    siblings_same = db.Column(db.String(10))
    siblings_private = db.Column(db.String(10))
    bus_route = db.Column(db.String(50))
    scholarship = db.Column(db.String(10))
    cocurricular_activities = db.Column(db.String(10))
    scholarship_details = db.Column(db.String(200))
    achievement_details = db.Column(db.String(200))

    # Tab 4 — Emergency Contact
    emergency_name = db.Column(db.String(200))
    emergency_contact = db.Column(db.String(20))
    emergency_relation = db.Column(db.String(50))
    emergency_relation_other = db.Column(db.String(100))

    # Tab 5 — IDPs Details
    is_refugee = db.Column(db.String(10))
    idp_status_id = db.Column(db.String(50))
    is_registered_refugee = db.Column(db.String(10))
    refugee_card = db.Column(db.String(50))

    # Tab 6 — Health Details
    has_major_disability = db.Column(db.String(10))
    disability_types = db.Column(db.String(200))
    major_disability = db.Column(db.String(200))
    has_mental_disability = db.Column(db.String(10))
    mental_disability_type = db.Column(db.String(50))
    mental_disability_other = db.Column(db.String(100))
    other_conditions = db.Column(db.String(200))
    visually_fit = db.Column(db.String(10))
    uses_glasses = db.Column(db.String(10))
    glass_prescription = db.Column(db.String(200))
    difficulty_seeing_board = db.Column(db.String(50))
    has_hearing_difficulties = db.Column(db.String(10))
    uses_hearing_aid = db.Column(db.String(10))
    hearing_aid_details = db.Column(db.String(200))
    difficulty_listening = db.Column(db.String(10))
    difficulty_walking = db.Column(db.String(10))
    uses_crutches_walker = db.Column(db.String(10))
    difficulty_reading_writing = db.Column(db.String(50))
    difficulty_remembering = db.Column(db.String(50))
    difficulty_concentrating = db.Column(db.String(50))
    basic_vaccination_completed = db.Column(db.String(10))

    # Tab 7 — Digital Access
    digital_device_at_home = db.Column(db.String(10))
    digital_device_type = db.Column(db.String(100))
    internet_at_home = db.Column(db.String(10))

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

def seed_options():
    """Load portal dropdown options from JSON into Jinja context."""
    with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if not session.get("role"):
        return redirect(url_for("login"))
    opts = seed_options()
    student_id = session.get("student_id")
    student = Student.query.get(student_id) if student_id else None
    return render_template("form.html", opts=opts, edit_id=student_id, student=student, is_locked=False)


@app.route("/form/<int:student_id>")
def edit_form(student_id):
    opts = seed_options()
    student = Student.query.get_or_404(student_id)
    return render_template("form.html", opts=opts, edit_id=student_id, student=student,
                           is_locked=student.locked and session.get("role") != "teacher")


# ---------------------------------------------------------------------------
# AJAX — Save tab data (create on Tab 1, update on later tabs)
# ---------------------------------------------------------------------------

FORM_FIELD_MAP = {
    "temp_id": None,
    "sub_sector_id": None,
    "present_sub_sector_id": None,
    "same_as_permanent_address": "same_address",
    "last_other_institution": "last_institution_other",
    "siblings_same_institution": "siblings_same",
    "other_medical_condition": "other_conditions",
}


@app.route("/api/save-tab", methods=["POST"])
def api_save_tab():
    payload = request.get_json()
    tab = payload.get("tab", 1)
    student_id = payload.get("student_id")
    data = payload.get("data", {})

    mapped = {}
    for form_key, value in data.items():
        db_col = FORM_FIELD_MAP.get(form_key, form_key)
        if db_col and hasattr(Student, db_col):
            mapped[db_col] = value

    if student_id:
        student = Student.query.get(student_id)
        if not student:
            return jsonify({"ok": False, "error": "Student not found"}), 404
        role = session.get("role")
        teacher_class = session.get("teacher_class")
        teacher_section = session.get("teacher_section")
        if role == "teacher" and not (
            student.class_id and teacher_class and
            student.class_id.ilike(teacher_class) if hasattr(student.class_id, "ilike") else
            (student.class_id == teacher_class and student.section_id == teacher_section)
        ):
            return jsonify({"ok": False, "error": "Student does not belong to your class"}), 403
        if student.locked and role != "teacher":
            return jsonify({"ok": False, "error": "Record is locked by teacher"}), 403
        for k, v in mapped.items():
            setattr(student, k, v)
    else:
        student = Student(**mapped)
        db.session.add(student)

    db.session.commit()
    return jsonify({"ok": True, "student_id": student.id})


@app.route("/api/final-submit", methods=["POST"])
def api_final_submit():
    payload = request.get_json()
    student_id = payload.get("student_id")
    if not student_id:
        return jsonify({"ok": False, "error": "No student_id"}), 400
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Student not found"}), 404
    student.submitted = True
    db.session.commit()
    return jsonify({"ok": True, "student_id": student.id})


@app.route("/submit", methods=["POST"])
def submit():
    data = request.form.to_dict()
    student = Student(**{k: v for k, v in data.items() if hasattr(Student, k)})
    student.submitted = True
    db.session.add(student)
    db.session.commit()
    flash("Student data submitted successfully!", "success")
    return redirect(url_for("success", student_id=student.id))


@app.route("/success/<int:student_id>")
def success(student_id):
    student = Student.query.get_or_404(student_id)
    return render_template("success.html", student=student)


@app.route("/students")
def list_students():
    students = Student.query.order_by(Student.created_at.desc()).all()
    return render_template("list.html", students=students)


@app.route("/students/<int:student_id>/json")
def student_json(student_id):
    student = Student.query.get_or_404(student_id)
    return jsonify(student.to_dict())


# ---------------------------------------------------------------------------
# Role-based access
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role", "student")
        name = request.form.get("name", "").strip()
        session["role"] = role
        session["user_name"] = name
        if role == "teacher":
            class_id = request.form.get("class_id", "").strip()
            section = request.form.get("section", "").strip()
            if not (name and class_id and section):
                flash("Please fill all fields: Name, Class, Section.", "danger")
                return redirect(url_for("login"))
            session["teacher_class"] = class_id
            session["teacher_section"] = section
            return redirect(url_for("teacher_dashboard"))
        class_id = request.form.get("class_id", "").strip()
        section = request.form.get("section", "").strip()
        roll_no = request.form.get("roll_no", "").strip()
        session["student_class"] = class_id
        session["student_section"] = section
        session["student_roll_no"] = roll_no
        if not (name and class_id and section and roll_no):
            flash("Please fill all fields: Name, Class, Section, Roll No.", "danger")
            return redirect(url_for("login"))
        student = Student.query.filter(
            Student.name.ilike(name),
            Student.class_id.ilike(class_id),
            Student.section_id.ilike(section),
            Student.roll_no.ilike(roll_no),
        ).first()
        if student:
            session["student_id"] = student.id
            return redirect(url_for("student_dashboard"))
        student = Student(
            name=name,
            class_id=class_id,
            section_id=section,
            roll_no=roll_no,
            role="student",
        )
        db.session.add(student)
        db.session.commit()
        session["student_id"] = student.id
        return redirect(url_for("student_dashboard"))
    return render_template("login.html")


@app.route("/student-dashboard")
def student_dashboard():
    name = session.get("user_name", "")
    role = session.get("role", "student")
    if not name:
        return redirect(url_for("login"))
    student_id = session.get("student_id")
    if student_id:
        student = Student.query.get(student_id)
        students = [student] if student else []
    else:
        students = []
    return render_template("dashboard.html", students=students, role=role, user_name=name)


@app.route("/teacher-dashboard")
def teacher_dashboard():
    name = session.get("user_name", "")
    role = session.get("role", "teacher")
    if not name:
        return redirect(url_for("login"))
    teacher_class = session.get("teacher_class")
    teacher_section = session.get("teacher_section")
    if teacher_class and teacher_section:
        students = Student.query.filter(
            Student.class_id.ilike(teacher_class),
            Student.section_id.ilike(teacher_section),
        ).order_by(Student.created_at.desc()).all()
    else:
        students = []
    return render_template("dashboard.html", students=students, role=role, user_name=name)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/lock/<int:student_id>", methods=["POST"])
def api_lock_student(student_id):
    if session.get("role") != "teacher":
        return jsonify({"ok": False, "error": "Teachers only"}), 403
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Not found"}), 404
    student.locked = True
    db.session.commit()
    return jsonify({"ok": True, "locked": True})


@app.route("/api/unlock/<int:student_id>", methods=["POST"])
def api_unlock_student(student_id):
    if session.get("role") != "teacher":
        return jsonify({"ok": False, "error": "Teachers only"}), 403
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Not found"}), 404
    student.locked = False
    db.session.commit()
    return jsonify({"ok": True, "locked": False})


# ---------------------------------------------------------------------------
# API — cascading dropdowns
# ---------------------------------------------------------------------------

@app.route("/api/districts/<province>")
def api_districts(province):
    district_map = {
        "Islamabad Capital Territory": ["Islamabad"],
        "Punjab": [
            "Attock", "Bahawalnagar", "Bahawalpur", "Bhakkar", "Chakwal", "Chiniot",
            "Dera Ghazi Khan", "Faisalabad", "Gujranwala", "Gujrat", "Hafizabad",
            "Jhang", "Jhelum", "Kasur", "Khanewal", "Khushab", "Lahore", "Layyah",
            "Lodhran", "Mandi Bahauddin", "Mianwali", "Multan", "Muzaffargarh",
            "Narowal", "Nankana Sahib", "Okara", "Pakpattan", "Rahim Yar Khan",
            "Rajanpur", "Rawalpindi", "Sahiwal", "Sargodha", "Sheikhupura",
            "Sialkot", "Toba Tek Singh", "Vehari", "Wazirabad"
        ],
        "Sindh": [
            "Badin", "Dadu", "Ghotki", "Hyderabad", "Jacobabad", "Jamshoro",
            "Karachi", "Kashmore", "Khairpur", "Larkana", "Matiari", "Mirpur Khas",
            "Naushahro Feroze", "Nawabshah", "Sanghar", "Shikarpur", "Sukkur",
            "Tando Allahyar", "Tando Muhammad Khan", "Thatta", "Umerkot"
        ],
        "Khyber Pakhtunkhwa": [
            "Abbottabad", "Bannu", "Barikot", "Battagram", "Buner", "Charsadda",
            "Chitral", "Dera Ismail Khan", "Dir Lower", "Dir Upper", "Haripur",
            "Kohat", "Kohistan", "Lakki Marwat", "Lower Dir", "Malakand", "Mansehra",
            "Mardan", "Nowshera", "Peshawar", "Shangla", "Swabi", "Swat",
            "Tank", "Torghar", "Upper Dir"
        ],
        "Balochistan": [
            "Awaran", "Barkhan", "Chagai", "Chaman", "Dera Bugti", "Gwadar",
            "Hub", "Jaffarabad", "Kalat", "Khuzdar", "Killa Saifullah", "Lasbela",
            "Lehri", "Loralai", "Mastung", "Nushki", "Panjgur", "Pasni",
            "Pishin", "Quetta", "Sibi", "Turbat", "Washuk", "Zhob"
        ],
        "Azad Jammu and Kashmir": [
            "Bagh", "Bhimbar", "Haveli", "Kotli", "Mirpur", "Muzaffarabad",
            "Neelum", "Pallandri", "Rawalakot", "Sudhnoti"
        ],
        "Gilgit-Baltistan": [
            "Gilgit", "Hunza", "Nagar", "Skardu", "Ghanche", "Shigar", "Roundu",
            "Astore", "Diamer", "Ghizer", "Kharmang"
        ],
        "Other than Pakistan": [],
    }
    districts = district_map.get(province, [])
    return jsonify(districts)


@app.route("/api/sub-sectors/<sector>")
def api_sub_sectors(sector):
    sub_sector_map = {
        "G-5": ["G-5/1", "G-5/2"],
        "G-6": ["G-6/1", "G-6/2", "G-6/3", "G-6/4"],
        "G-7": ["G-7/1", "G-7/2", "G-7/3", "G-7/4"],
        "G-8": ["G-8/1", "G-8/2", "G-8/3", "G-8/4"],
        "G-9": ["G-9/1", "G-9/2", "G-9/3", "G-9/4"],
        "G-10": ["G-10/1", "G-10/2", "G-10/3", "G-10/4"],
        "G-11": ["G-11/1", "G-11/2", "G-11/3", "G-11/4"],
        "G-12": ["G-12/1", "G-12/2", "G-12/3", "G-12/4"],
        "G-13": ["G-13/1", "G-13/2", "G-13/3", "G-13/4"],
        "G-14": ["G-14/1", "G-14/2", "G-14/3", "G-14/4"],
        "G-15": ["G-15/1", "G-15/2", "G-15/3", "G-15/4"],
        "G-16": ["G-16/1", "G-16/2", "G-16/3", "G-16/4"],
        "G-17": ["G-17/1", "G-17/2", "G-17/3", "G-17/4"],
        "F-5": ["F-5/1", "F-5/2"],
        "F-6": ["F-6/1", "F-6/2", "F-6/3", "F-6/4"],
        "F-7": ["F-7/1", "F-7/2", "F-7/3", "F-7/4"],
        "F-8": ["F-8/1", "F-8/2", "F-8/3", "F-8/4"],
        "F-9": [],
        "F-10": ["F-10/1", "F-10/2", "F-10/3", "F-10/4"],
        "F-11": ["F-11/1", "F-11/2", "F-11/3", "F-11/4"],
        "F-12": ["F-12/1", "F-12/2", "F-12/3", "F-12/4"],
        "F-13": ["F-13/1", "F-13/2", "F-13/3", "F-13/4"],
        "E-7": ["E-7/1", "E-7/2", "E-7/3", "E-7/4"],
        "E-8": ["E-8/1", "E-8/2", "E-8/3", "E-8/4"],
        "E-9": ["E-9/1", "E-9/2", "E-9/3", "E-9/4"],
        "E-11": ["E-11/1", "E-11/2", "E-11/3", "E-11/4"],
        "E-12": ["E-12/1", "E-12/2", "E-12/3", "E-12/4"],
        "H-8": ["H-8/1", "H-8/2", "H-8/3", "H-8/4"],
        "H-9": ["H-9/1", "H-9/2", "H-9/3", "H-9/4"],
        "H-10": ["H-10/1", "H-10/2", "H-10/3", "H-10/4"],
        "H-11": ["H-11/1", "H-11/2", "H-11/3", "H-11/4"],
        "H-12": ["H-12/1", "H-12/2", "H-12/3", "H-12/4"],
        "H-13": ["H-13/1", "H-13/2", "H-13/3", "H-13/4"],
        "I-8": ["I-8/1", "I-8/2", "I-8/3", "I-8/4"],
        "I-9": ["I-9/1", "I-9/2", "I-9/3", "I-9/4"],
        "I-10": ["I-10/1", "I-10/2", "I-10/3", "I-10/4"],
        "I-11": ["I-11/1", "I-11/2", "I-11/3", "I-11/4"],
        "I-12": ["I-12/1", "I-12/2", "I-12/3", "I-12/4"],
        "I-13": ["I-13/1", "I-13/2", "I-13/3", "I-13/4"],
        "I-14": ["I-14/1", "I-14/2", "I-14/3", "I-14/4"],
        "I-15": ["I-15/1", "I-15/2", "I-15/3", "I-15/4"],
        "I-16": ["I-16/1", "I-16/2", "I-16/3", "I-16/4"],
        "I-17": ["I-17/1", "I-17/2", "I-17/3", "I-17/4"],
        "B-12": ["B-12/1", "B-12/2", "B-12/3", "B-12/4"],
    }
    return jsonify(sub_sector_map.get(sector, []))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
