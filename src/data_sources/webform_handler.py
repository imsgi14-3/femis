"""Reads student data from the FEMIS Web SQLite database."""
import sqlite3
from pathlib import Path
from src.utils.logger import setup_logger

logger = setup_logger("webform_handler")

DB_PATH = Path(__file__).parent.parent.parent / "femis-web" / "instance" / "femis.db"

# If running from inside femis-web, also check the local path
DB_PATH_LOCAL = Path(__file__).parent.parent.parent / "femis-web" / "femis.db"


class WebFormHandler:
    """Reads student records from the SQLite database created by the Flask web app."""

    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path) if db_path else self._find_db()

    def _find_db(self) -> Path:
        if DB_PATH.exists():
            return DB_PATH
        if DB_PATH_LOCAL.exists():
            return DB_PATH_LOCAL
        # Search in common Flask locations
        search = [
            Path("femis-web/femis.db"),
            Path("femis-web/instance/femis.db"),
            Path("../femis-web/femis.db"),
            Path("../femis-web/instance/femis.db"),
        ]
        for p in search:
            if p.exists():
                return p.resolve()
        raise FileNotFoundError(
            f"SQLite database not found. Looked in: {DB_PATH}, {DB_PATH_LOCAL}, {search}"
        )

    def read_by_id(self, student_id: int) -> dict | None:
        """Read a single student record by ID."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            logger.warning(f"No student found with id={student_id}")
            return None
        student = dict(row)
        student.pop("id", None)
        student.pop("created_at", None)
        return student

    def read_all(self, limit: int = None) -> list[dict]:
        """Read all student records from the database.
        Returns list of dicts matching the field names expected by FormFiller.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM students ORDER BY created_at ASC"
        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        students = []
        for row in rows:
            student = dict(row)
            # Remove metadata columns
            student.pop("id", None)
            student.pop("created_at", None)
            students.append(student)

        logger.info(f"Loaded {len(students)} students from webform database")
        return students

    def read_unprocessed(self, limit: int = None) -> list[dict]:
        """Read students that haven't been processed by the bot yet.
        Looks for a 'processed' column or checks if student exists in a processed log.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check if processed column exists
        cursor.execute("PRAGMA table_info(students)")
        columns = [col[1] for col in cursor.fetchall()]

        if "processed" in columns:
            query = "SELECT * FROM students WHERE processed = 0 OR processed IS NULL ORDER BY created_at ASC"
            if limit:
                query += f" LIMIT {limit}"
            cursor.execute(query)
        else:
            query = "SELECT * FROM students ORDER BY created_at ASC"
            if limit:
                query += f" LIMIT {limit}"
            cursor.execute(query)

        rows = cursor.fetchall()
        conn.close()

        students = []
        for row in rows:
            student = dict(row)
            student.pop("id", None)
            student.pop("created_at", None)
            student.pop("processed", None)
            students.append(student)

        logger.info(f"Loaded {len(students)} unprocessed students from webform database")
        return students

    def mark_processed(self, student_id: int):
        """Mark a student record as processed by the bot."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Add processed column if it doesn't exist
        cursor.execute("PRAGMA table_info(students)")
        columns = [col[1] for col in cursor.fetchall()]
        if "processed" not in columns:
            cursor.execute("ALTER TABLE students ADD COLUMN processed INTEGER DEFAULT 0")

        cursor.execute("UPDATE students SET processed = 1 WHERE id = ?", (student_id,))
        conn.commit()
        conn.close()
        logger.info(f"Marked student #{student_id} as processed")

    def get_student_count(self) -> int:
        """Return total number of students in database."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM students")
        count = cursor.fetchone()[0]
        conn.close()
        return count
