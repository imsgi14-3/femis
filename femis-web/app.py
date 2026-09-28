"""FEMIS Web — Student Data Collection Form
Flask app replicating the FEMIS portal's 7-tab student form.
Parents/teachers fill this; the bot reads from the DB and fills the real portal.
"""
import json, os, re, sqlite3
from pathlib import Path
from flask import (Flask, render_template, request, jsonify, redirect, url_for,
                   flash, session, send_file)
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "femis-web-dev-key-change-in-prod")
_basedir = os.path.abspath(os.path.dirname(__file__))
_instance_dir = os.path.join(_basedir, "instance")
os.makedirs(_instance_dir, exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(_instance_dir, "femis.db"),
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

db = SQLAlchemy(app)

OPTIONS_PATH = Path(__file__).parent / "portal_options.json"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Phase 3B.3: latest modification time (UTC, naive — same convention as created_at).
    # Version/staleness marker only — bot-job snapshots are separate (docs/phase3b3-schema.md).
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
    sub_sector_id = db.Column(db.String(50))
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
    present_sub_sector_id = db.Column(db.String(50))
    present_village_id = db.Column(db.String(100))
    present_housing_society_id = db.Column(db.String(100))
    religion = db.Column(db.String(50))
    religion_id = db.Column(db.String(50))
    language_id = db.Column(db.String(50))
    blood_group = db.Column(db.String(10))
    email = db.Column(db.String(100))
    mother_language_other = db.Column(db.String(100))
    address = db.Column(db.String(500))
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
    guardian_email = db.Column(db.String(100))
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
    transport = db.Column(db.String(50))
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
    disability_certificate = db.Column(db.String(500))
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


class Teacher(db.Model):
    __tablename__ = "teachers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    class_id = db.Column(db.String(50), nullable=False)
    section_id = db.Column(db.String(20), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="teacher")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# ---------------------------------------------------------------------------
# Bot job / attempt storage (Phase 3B.3 — schema only; no API in this phase)
# ---------------------------------------------------------------------------
# One row = one execution attempt (one-to-many per student). Historical rows
# are never overwritten; retry creates a new attempt_number.
# Field classification: docs/phase3b3-schema.md

BOT_JOB_OPEN_STATUSES = ("pending", "claimed", "running")
BOT_JOB_TERMINAL_STATUSES = ("success", "failed", "cancelled")
BOT_JOB_STATUSES = BOT_JOB_OPEN_STATUSES + BOT_JOB_TERMINAL_STATUSES
BOT_JOB_FAILURE_CATEGORIES = (
    "validation",
    "field_mapping",
    "browser",
    "network",
    "femis",
    "captcha",
    "timeout",
    "auth_portal",
    "cancelled_by_operator",
    "unknown",
)


class BotJob(db.Model):
    __tablename__ = "bot_jobs"

    # --- identity ---
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number = db.Column(db.Integer, nullable=False)

    # --- lifecycle ---
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    claimed_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    # --- snapshot / version (materialized at claim; null until then) ---
    student_data_version = db.Column(db.DateTime)
    snapshot_json = db.Column(db.Text)
    snapshot_materialized_at = db.Column(db.DateTime)

    # --- claim / lease (values configurable at runtime — not baked in) ---
    claimed_by = db.Column(db.String(80))
    lease_expires_at = db.Column(db.DateTime)
    last_heartbeat_at = db.Column(db.DateTime)
    claim_generation = db.Column(db.Integer, nullable=False, default=0)

    # --- progress ---
    current_tab = db.Column(db.Integer)
    last_completed_tab = db.Column(db.Integer)

    # --- failure / outcome ---
    failure_category = db.Column(db.String(40))
    failed_tab = db.Column(db.Integer)
    failed_field = db.Column(db.String(200))
    error_message = db.Column(db.Text)
    outcome_known = db.Column(db.Boolean, nullable=True)
    bot_result_code = db.Column(db.String(30))

    # --- success evidence (Finish + indicator; schema never equates fill_success with success) ---
    finish_clicked = db.Column(db.Boolean)
    indicator_detected = db.Column(db.Boolean)

    # --- retry / audit ---
    prior_attempt_id = db.Column(db.Integer, db.ForeignKey("bot_jobs.id", ondelete="SET NULL"))
    created_by = db.Column(db.String(100))
    requested_at = db.Column(db.DateTime)
    retry_requested_at = db.Column(db.DateTime)
    idempotency_key = db.Column(db.String(120))

    __table_args__ = (
        db.UniqueConstraint("student_id", "attempt_number", name="uq_bot_jobs_student_attempt"),
        db.UniqueConstraint("idempotency_key", name="uq_bot_jobs_idempotency_key"),
        db.CheckConstraint(
            "status IN ('pending','claimed','running','success','failed','cancelled')",
            name="ck_bot_jobs_status",
        ),
        db.CheckConstraint(
            "failure_category IS NULL OR failure_category IN "
            "('validation','field_mapping','browser','network','femis','captcha',"
            "'timeout','auth_portal','cancelled_by_operator','unknown')",
            name="ck_bot_jobs_failure_category",
        ),
        db.CheckConstraint("attempt_number >= 1", name="ck_bot_jobs_attempt_number"),
        db.CheckConstraint(
            "status <> 'success' OR (COALESCE(outcome_known, 0) = 1"
            " AND COALESCE(finish_clicked, 0) = 1 AND COALESCE(indicator_detected, 0) = 1)",
            name="ck_bot_jobs_success_evidence",
        ),
        db.CheckConstraint(
            "snapshot_json IS NULL OR student_data_version IS NOT NULL",
            name="ck_bot_jobs_snapshot_requires_version",
        ),
        # At most one open job per student (DB-level, race-safe).
        db.Index(
            "uq_bot_jobs_open_per_student",
            "student_id",
            unique=True,
            sqlite_where=db.text("status IN ('pending','claimed','running')"),
        ),
        db.Index("ix_bot_jobs_status_created", "status", "created_at"),
        db.Index("ix_bot_jobs_lease", "status", "lease_expires_at"),
        db.Index("ix_bot_jobs_student_created", "student_id", "created_at"),
    )

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ---------------------------------------------------------------------------
# Schema bootstrap / lightweight migration (runs after models are registered)
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()
    # Lightweight migration: add columns missing from older SQLite DBs
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(students)"))}
            for col in ("sub_sector_id", "present_sub_sector_id"):
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE students ADD COLUMN {col} VARCHAR(50)"))
                    cols.add(col)
            # Phase 3B.3: students.updated_at (UTC version marker; see docs/phase3b3-schema.md)
            if "updated_at" not in cols:
                conn.execute(text("ALTER TABLE students ADD COLUMN updated_at DATETIME"))
            conn.execute(text(
                "UPDATE students SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
                "WHERE updated_at IS NULL"
            ))
            # One record per B-Form/CNIC (portal rule: "B-Form Number has already been
            # taken"). Normalized digits-only uniqueness; empty values stay exempt.
            # Runs every startup — CREATE INDEX IF NOT EXISTS is idempotent, and
            # db.create_all() never adds indexes to pre-existing tables.
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_students_b_form ON students ("
                "replace(replace(replace(b_form, '-', ''), ' ', ''), '.', '')) "
                "WHERE b_form IS NOT NULL AND b_form <> ''"
            ))
            # RBAC: teachers.role ('admin' | 'teacher') — additive + idempotent,
            # preserves existing rows (defaulted to 'teacher').
            tcols = {r[1] for r in conn.execute(text("PRAGMA table_info(teachers)"))}
            if "role" not in tcols:
                conn.execute(text(
                    "ALTER TABLE teachers ADD COLUMN role VARCHAR(20) "
                    "NOT NULL DEFAULT 'teacher'"
                ))
            conn.commit()
    except Exception as e:
        print(f"schema migration warning: {e}", flush=True)

    # First-boot admin seed — env-driven (FEMIS_ADMIN_NAME / FEMIS_ADMIN_PASSWORD),
    # never overwrites an existing admin. Values live in .env (local) or the
    # PythonAnywhere Web-tab environment, never in the repo.
    _admin_name = (os.environ.get("FEMIS_ADMIN_NAME") or "").strip()
    _admin_pass = (os.environ.get("FEMIS_ADMIN_PASSWORD") or "").strip()
    if (_admin_name and _admin_pass
            and Teacher.query.filter(Teacher.role == "admin").count() == 0):
        _seed_admin = Teacher(name=_admin_name, class_id="-", section_id="-", role="admin")
        _seed_admin.set_password(_admin_pass)
        db.session.add(_seed_admin)
        db.session.commit()
        print(f"seeded admin account: {_admin_name}", flush=True)


# ---------------------------------------------------------------------------
# Phase 3B.4 — bot-job API blueprint (store/lifecycle only; no auto-create)
# ---------------------------------------------------------------------------

from job_api import bp as job_api_bp  # noqa: E402

app.register_blueprint(job_api_bp)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

def seed_options():
    """Load portal dropdown options from JSON into Jinja context."""
    with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------

def _teacher_owns(student):
    """Ownership = exact class + section match (case-insensitive)."""
    tc = session.get("teacher_class")
    ts = session.get("teacher_section")
    if not (tc and ts and student.class_id and student.section_id):
        return False
    return (student.class_id.lower() == tc.lower()
            and student.section_id.lower() == ts.lower())


def _can_modify(student):
    """admin -> all; teacher -> own class+section; student -> own record."""
    role = session.get("role")
    if role == "admin":
        return True
    if role == "teacher":
        return _teacher_owns(student)
    if role == "student":
        return session.get("student_id") == student.id
    return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    role = session.get("role")
    if not role:
        return redirect(url_for("login"))
    if role in ("teacher", "admin"):
        return redirect(url_for("teacher_dashboard"))
    return redirect(url_for("student_dashboard"))


@app.route("/form")
def new_form():
    role = session.get("role")
    if not role:
        return redirect(url_for("login"))
    student_id = session.get("student_id")
    if role == "student" and student_id:
        return redirect(url_for("edit_form", student_id=student_id))
    return render_template("form.html", opts=seed_options(), edit_id=None,
                           student=None, is_locked=False)


@app.route("/form/<int:student_id>")
def edit_form(student_id):
    if not session.get("role"):
        return redirect(url_for("login"))
    opts = seed_options()
    student = Student.query.get_or_404(student_id)
    if session.get("role") == "student" and session.get("student_id") != student_id:
        return redirect(url_for("student_dashboard"))
    if not _can_modify(student):
        return ("Forbidden", 403)
    return render_template("form.html", opts=opts, edit_id=student_id, student=student,
                           is_locked=student.locked and session.get("role") not in ("teacher", "admin"))


# ---------------------------------------------------------------------------
# AJAX — Save tab data (create on Tab 1, update on later tabs)
# ---------------------------------------------------------------------------

FORM_FIELD_MAP = {
    "temp_id": None,
    "same_as_permanent_address": "same_address",
    "last_other_institution": "last_institution_other",
    "siblings_same_institution": "siblings_same",
    "other_medical_condition": "other_conditions",
    "cocurricular_details": "achievement_details",
    "result_percentage": "last_class_result",
    "digital_device_type[]": "digital_device_type",
    "present_address": "present_address_other",
    "transport_facility": "transport",
    "refugee_card_number": "refugee_card",
    "disability_types[]": "disability_types",
}


_MDY_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
DATE_COLUMNS = ("date_of_birth", "date_of_admission")


def _normalize_date_value(value):
    """MM/DD/YYYY (the form's calendar display format) -> canonical ISO.

    ISO strings and anything else pass through untouched: the flatpickr
    calendar on the PA form posts MM/DD/YYYY, legacy rows already store
    ISO (YYYY-MM-DD), and non-date strings stay as they are so existing
    callers keep working.
    """
    if not isinstance(value, str):
        return value
    m = _MDY_DATE.match(value.strip())
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return value


def _map_form_data(data):
    mapped = {}
    for form_key, value in (data or {}).items():
        db_col = FORM_FIELD_MAP.get(form_key, form_key)
        if db_col and hasattr(Student, db_col):
            if db_col in DATE_COLUMNS:
                value = _normalize_date_value(value)
            mapped[db_col] = value
    return mapped


@app.template_filter("mmdd")
def _mmdd_filter(value):
    """ISO YYYY-MM-DD -> MM/DD/YYYY for display; anything else passes through."""
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        y, m, d = value.split("-")
        return f"{m}/{d}/{y}"
    return value or ""


def _b_form_digits(value):
    return re.sub(r"\D", "", value or "")


def _b_form_conflict(b_form, exclude_id=None):
    """Return the student row already holding this B-Form/CNIC, or None.

    Compares digits-only so '35202-1234567-1' == '3520212345671'. Empty/None
    never conflicts (students without a B-Form are allowed to repeat).
    """
    target = _b_form_digits(b_form)
    if not target:
        return None
    query = Student.query.filter(Student.b_form.isnot(None))
    if exclude_id:
        query = query.filter(Student.id != exclude_id)
    for row in query.all():
        if _b_form_digits(row.b_form) == target:
            return row
    return None


def _b_form_error(holder, b_form):
    return (
        f"B-Form/CNIC {b_form} is already used by student '{holder.name}' "
        f"(id {holder.id}). The portal keeps one record per CNIC — edit that "
        f"record instead of creating a duplicate."
    )


def _admission_norm(value):
    return re.sub(r"\s+", "", value or "").upper()


def _admission_conflict(admission_number, exclude_id=None):
    """Return the student row already holding this admission number, or None.

    Compares whitespace-stripped + case-insensitive so 'adm-001 ' == 'ADM-001'.
    Empty/None never conflicts (students without one may repeat).
    """
    target = _admission_norm(admission_number)
    if not target:
        return None
    query = Student.query.filter(Student.admission_number.isnot(None))
    if exclude_id:
        query = query.filter(Student.id != exclude_id)
    for row in query.all():
        if _admission_norm(row.admission_number) == target:
            return row
    return None


def _admission_error(holder, value):
    return (
        f"Admission Number {value} is already used by student '{holder.name}' "
        f"(id {holder.id}). One admission number per student — edit that "
        f"record instead of creating a duplicate."
    )


def _uniqueness_error(mapped, exclude_id=None):
    """409 message if mapped b_form/admission_number duplicates a row, else None."""
    if "b_form" in mapped:
        holder = _b_form_conflict(mapped["b_form"], exclude_id=exclude_id)
        if holder:
            return _b_form_error(holder, mapped["b_form"])
    if "admission_number" in mapped:
        holder = _admission_conflict(mapped["admission_number"], exclude_id=exclude_id)
        if holder:
            return _admission_error(holder, mapped["admission_number"])
    return None


@app.route("/api/save-tab", methods=["POST"])
def api_save_tab():
    payload = request.get_json()
    tab = payload.get("tab", 1)
    student_id = payload.get("student_id")
    data = payload.get("data", {})

    mapped = _map_form_data(data)

    if student_id:
        student = Student.query.get(student_id)
        if not student:
            return jsonify({"ok": False, "error": "Student not found"}), 404
        if not _can_modify(student):
            return jsonify({"ok": False, "error": "You are not allowed to modify this record"}), 403
        if student.locked and session.get("role") not in ("teacher", "admin"):
            return jsonify({"ok": False, "error": "Record is locked by teacher"}), 403
        err = _uniqueness_error(mapped, exclude_id=student.id)
        if err:
            return jsonify({"ok": False, "error": err}), 409
        for k, v in mapped.items():
            setattr(student, k, v)
    else:
        err = _uniqueness_error(mapped)
        if err:
            return jsonify({"ok": False, "error": err}), 409
        student = Student(**mapped)
        db.session.add(student)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        err = _uniqueness_error(mapped, exclude_id=student.id if student_id else None)
        if err:
            return jsonify({"ok": False, "error": err}), 409
        raise
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
    if not _can_modify(student):
        return jsonify({"ok": False, "error": "You are not allowed to modify this record"}), 403
    mapped = _map_form_data(payload.get("data"))
    err = _uniqueness_error(mapped, exclude_id=student.id)
    if err:
        return jsonify({"ok": False, "error": err}), 409
    for k, v in mapped.items():
        setattr(student, k, v)
    student.submitted = True
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        err = _uniqueness_error(mapped, exclude_id=student.id)
        if err:
            return jsonify({"ok": False, "error": err}), 409
        raise
    redirect_url = ("/student-dashboard" if session.get("role") == "student"
                    else url_for("success", student_id=student.id))
    return jsonify({"ok": True, "student_id": student.id, "redirect": redirect_url})


@app.route("/api/upload-file", methods=["POST"])
def api_upload_file():
    student_id = request.form.get("student_id")
    field_name = request.form.get("field_name", "file")
    if not student_id:
        return jsonify({"ok": False, "error": "No student_id"}), 400
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Student not found"}), 404
    if not _can_modify(student):
        return jsonify({"ok": False, "error": "You are not allowed to modify this record"}), 403
    if field_name not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    f = request.files[field_name]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400
    ext = Path(f.filename).suffix
    safe_name = f"student_{student_id}_{field_name}{ext}"
    save_path = UPLOAD_FOLDER / safe_name
    f.save(str(save_path))
    setattr(student, field_name, safe_name)
    db.session.commit()
    return jsonify({"ok": True, "filename": safe_name})


@app.route("/submit", methods=["POST"])
def submit():
    data = request.form.to_dict()
    for dk in DATE_COLUMNS:
        if dk in data:
            data[dk] = _normalize_date_value(data[dk])
    uniq = {k: v for k, v in data.items() if k in ("b_form", "admission_number")}
    err = _uniqueness_error(uniq)
    if err:
        flash(err, "error")
        return redirect(url_for("index"))
    student = Student(**{k: v for k, v in data.items() if hasattr(Student, k)})
    student.submitted = True
    db.session.add(student)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        err = _uniqueness_error(uniq)
        if err:
            flash(err, "error")
        else:
            raise
        return redirect(url_for("index"))
    flash("Student data submitted successfully!", "success")
    return redirect(url_for("success", student_id=student.id))


@app.route("/success/<int:student_id>")
def success(student_id):
    student = Student.query.get_or_404(student_id)
    return render_template("success.html", student=student)


@app.route("/students")
def list_students():
    role = session.get("role")
    if not role:
        return redirect(url_for("login"))
    q = Student.query
    if role == "teacher":
        q = q.filter(Student.class_id.ilike(session.get("teacher_class") or ""),
                     Student.section_id.ilike(session.get("teacher_section") or ""))
    elif role == "student":
        q = q.filter(Student.id == session.get("student_id"))
    students = q.order_by(Student.created_at.desc()).all()
    return render_template("list.html", students=students)


@app.route("/students/<int:student_id>/json")
def student_json(student_id):
    student = Student.query.get_or_404(student_id)
    if not session.get("role"):
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    if not _can_modify(student):
        return jsonify({"ok": False, "error": "Not allowed"}), 403
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
        if role == "admin":
            password = request.form.get("password", "")
            if not (name and password):
                flash("Please fill Name and Password.", "danger")
                return redirect(url_for("login"))
            admin = Teacher.query.filter(
                Teacher.role == "admin", Teacher.name.ilike(name)
            ).first()
            if not admin or not admin.check_password(password):
                flash("Invalid admin credentials.", "danger")
                return redirect(url_for("login"))
            session["role"] = "admin"
            session["teacher_id"] = admin.id
            session["teacher_class"] = admin.class_id
            session["teacher_section"] = admin.section_id
            return redirect(url_for("teacher_dashboard"))
        if role == "teacher":
            password = request.form.get("password", "")
            class_id = request.form.get("class_id", "").strip()
            section = request.form.get("section", "").strip()
            if not (name and password and class_id and section):
                flash("Please fill all fields: Name, Password, Class, Section.", "danger")
                return redirect(url_for("login"))
            teacher = Teacher.query.filter(
                Teacher.name.ilike(name),
                Teacher.class_id.ilike(class_id),
                Teacher.section_id.ilike(section),
            ).first()
            if not teacher or not teacher.check_password(password):
                flash("Invalid credentials. Check name, password, class, section.", "danger")
                return redirect(url_for("login"))
            session["teacher_id"] = teacher.id
            session["teacher_class"] = class_id
            session["teacher_section"] = section
            if teacher.role == "admin":
                session["role"] = "admin"
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
    return render_template(
        "login.html",
        admin_exists=Teacher.query.filter(Teacher.role == "admin").count() > 0,
    )


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
    teachers = []
    if role == "admin":
        students = Student.query.order_by(Student.created_at.desc()).all()
        teachers = (Teacher.query.filter(Teacher.role != "admin")
                    .order_by(Teacher.created_at.desc()).all())
    elif teacher_class and teacher_section:
        students = Student.query.filter(
            Student.class_id.ilike(teacher_class),
            Student.section_id.ilike(teacher_section),
        ).order_by(Student.created_at.desc()).all()
    else:
        students = []
    return render_template("dashboard.html", students=students, teachers=teachers,
                           role=role, user_name=name)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/register-teacher", methods=["POST"])
def api_register_teacher():
    if session.get("role") != "admin":
        return jsonify({"ok": False, "error": "Only the admin can create teachers"}), 403
    data = request.get_json()
    name = data.get("name", "").strip()
    password = data.get("password", "")
    class_id = data.get("class_id", "").strip()
    section = data.get("section", "").strip()
    if not (name and password and class_id and section):
        return jsonify({"ok": False, "error": "All fields required"}), 400
    existing = Teacher.query.filter(
        Teacher.name.ilike(name),
        Teacher.class_id.ilike(class_id),
        Teacher.section_id.ilike(section),
    ).first()
    if existing:
        return jsonify({"ok": False, "error": "Teacher already exists"}), 409
    teacher = Teacher(name=name, class_id=class_id, section_id=section)
    teacher.set_password(password)
    db.session.add(teacher)
    db.session.commit()
    return jsonify({"ok": True, "teacher_id": teacher.id})


@app.route("/api/setup-admin", methods=["POST"])
def api_setup_admin():
    if Teacher.query.filter(Teacher.role == "admin").count() > 0:
        return jsonify({"ok": False, "error": "Admin already exists."}), 400
    data = request.get_json()
    name = data.get("name", "").strip()
    password = data.get("password", "")
    if not (name and password):
        return jsonify({"ok": False, "error": "Name and password required"}), 400
    teacher = Teacher(
        name=name,
        class_id=data.get("class_id") or "-",
        section_id=data.get("section") or "-",
        role="admin",
    )
    teacher.set_password(password)
    db.session.add(teacher)
    db.session.commit()
    session["role"] = "admin"
    session["user_name"] = name
    session["teacher_id"] = teacher.id
    session["teacher_class"] = teacher.class_id
    session["teacher_section"] = teacher.section_id
    return jsonify({"ok": True, "teacher_id": teacher.id})


@app.route("/api/lock/<int:student_id>", methods=["POST"])
def api_lock_student(student_id):
    if session.get("role") not in ("teacher", "admin"):
        return jsonify({"ok": False, "error": "Teachers only"}), 403
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Not found"}), 404
    if session.get("role") == "teacher" and not _teacher_owns(student):
        return jsonify({"ok": False, "error": "Not your class/section"}), 403
    student.locked = True
    db.session.commit()
    return jsonify({"ok": True, "locked": True})


@app.route("/api/unlock/<int:student_id>", methods=["POST"])
def api_unlock_student(student_id):
    if session.get("role") not in ("teacher", "admin"):
        return jsonify({"ok": False, "error": "Teachers only"}), 403
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Not found"}), 404
    if session.get("role") == "teacher" and not _teacher_owns(student):
        return jsonify({"ok": False, "error": "Not your class/section"}), 403
    student.locked = False
    db.session.commit()
    return jsonify({"ok": True, "locked": False})


@app.route("/api/delete/<int:student_id>", methods=["POST"])
def api_delete_student(student_id):
    role = session.get("role")
    if role not in ("teacher", "admin"):
        return jsonify({"ok": False, "error": "Teachers only"}), 403
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Not found"}), 404
    if role == "teacher" and not _teacher_owns(student):
        return jsonify({"ok": False, "error": "Not your class/section"}), 403
    # SQLite FK pragma is off -> delete bot_jobs explicitly (incl. attempts).
    n_jobs = BotJob.query.filter(BotJob.student_id == student_id) \
        .delete(synchronize_session=False)
    for p in UPLOAD_FOLDER.glob(f"student_{student_id}_*"):
        try:
            p.unlink()
        except OSError:
            pass
    db.session.delete(student)
    db.session.commit()
    return jsonify({"ok": True, "deleted_jobs": n_jobs})


# ---------------------------------------------------------------------------
# Admin — teacher management (create lives at /api/register-teacher)
# ---------------------------------------------------------------------------

@app.route("/api/admin/teachers/<int:teacher_id>/delete", methods=["POST"])
def api_admin_delete_teacher(teacher_id):
    if session.get("role") != "admin":
        return jsonify({"ok": False, "error": "Admin only"}), 403
    teacher = Teacher.query.get(teacher_id)
    if not teacher:
        return jsonify({"ok": False, "error": "Not found"}), 404
    if teacher.role == "admin":
        return jsonify({"ok": False, "error": "Admin account cannot be deleted"}), 403
    db.session.delete(teacher)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/teachers/<int:teacher_id>/reset-password", methods=["POST"])
def api_admin_reset_teacher_password(teacher_id):
    if session.get("role") != "admin":
        return jsonify({"ok": False, "error": "Admin only"}), 403
    teacher = Teacher.query.get(teacher_id)
    if not teacher:
        return jsonify({"ok": False, "error": "Not found"}), 404
    if teacher.role == "admin":
        return jsonify({"ok": False,
                        "error": "Admin password is managed via environment variable"}), 403
    password = (request.get_json() or {}).get("password", "").strip()
    if not password:
        return jsonify({"ok": False, "error": "New password required"}), 400
    teacher.set_password(password)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/export")
def api_admin_export():
    """Full-DB snapshot for the local pull script (tools/sync_from_portal.py).

    Uses sqlite3's backup API — a consistent copy even during live writes.
    The temp file is deleted once the response is fully sent.
    """
    if not session.get("role"):
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    if session.get("role") != "admin":
        return jsonify({"ok": False, "error": "Admin only"}), 403
    src_path = db.engine.url.database
    if not src_path:
        return jsonify({"ok": False, "error": "SQLite export requires an SQLite database"}), 500
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    snapshot = Path(_instance_dir) / f"femis_export_{ts}.db"
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(str(snapshot))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    resp = send_file(snapshot, as_attachment=True,
                     download_name=f"femis_{ts}.db",
                     mimetype="application/octet-stream")
    resp.call_on_close(lambda: snapshot.unlink(missing_ok=True))
    return resp


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
        "Khyber Pakhtonkhawa": [
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
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
