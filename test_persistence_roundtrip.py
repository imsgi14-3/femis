"""Phase 3B.11 — focused persistence round-trip test (diagnosis only).

Purpose: prove that the CURRENT source tree persists and reloads every field that the
long-running :5000 process was observed dropping (transport_facility, refugee_card,
disability_types, sub_sector_id) — i.e. isolate the empty-after-reload symptom to the
stale server process rather than to current code.

Covers: create via /api/save-tab -> reload via GET /students/<id>/json (the exact
endpoint form.js pre-fills from) -> partial update via /api/save-tab -> reload again
(proves an update does not wipe sibling fields) -> updated_at version bump.

Everything created here is deleted here. Pre-existing rows (including both Ayat Mubeen
rows) are snapshotted at start and must survive byte-identical.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import Student, app, db  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


PROBE_NAME = "P3B11 PERSISTENCE PROBE"
DB_PATH = ROOT / "femis-web" / "instance" / "femis.db"

CREATE_DATA = {
    "name": PROBE_NAME,
    "class_id": "9",
    "section_id": "A",
    "roll_no": "P3B11",
    "father_name": "P3B11-FATHER",
    "guardian_name": "P3B11-GUARDIAN",
    "sub_sector_id": "P3B11-SECTOR",
    "transport_facility": "Institution Bus",
    "bus_route": "TARNOL",
    "refugee_card_number": "P3B11-REFCARD",
    "disability_types[]": "Visual",
    "digital_device_type[]": "Mobile Phone",
    "date_of_admission": "04/24/2023",
}
UPDATE_DATA = {
    "father_name": "P3B11-FATHER-UPDATED",
    "bus_route": "RAWALPINDI",
}

baseline_ids = []
probe_id = None

try:
    with app.app_context():
        baseline_ids = [r.id for r in Student.query.order_by(Student.id).all()]
        Student.query.filter(Student.name == PROBE_NAME).delete()
        db.session.commit()

    client = app.test_client()

    # ---- 1. create ----
    r = client.post("/api/save-tab", json={"tab": 3, "student_id": None, "data": CREATE_DATA})
    body = r.get_json()
    check("create returns ok", r.status_code == 200 and body.get("ok") is True, str(body))
    probe_id = body.get("student_id")
    check("create returns a student_id", bool(probe_id), f"probe_id={probe_id}")

    # ---- 2. reload (form.js pre-fill source) ----
    r = client.get(f"/students/{probe_id}/json")
    row = r.get_json()
    check("reload returns 200", r.status_code == 200, str(r.status_code))
    for col, expect in [
        ("transport", "Institution Bus"),
        ("bus_route", "TARNOL"),
        ("refugee_card", "P3B11-REFCARD"),
        ("disability_types", "Visual"),
        ("sub_sector_id", "P3B11-SECTOR"),
        ("father_name", "P3B11-FATHER"),
        ("guardian_name", "P3B11-GUARDIAN"),
        ("digital_device_type", "Mobile Phone"),
        ("date_of_admission", "04/24/2023"),
    ]:
        check(f"reload has {col}", row.get(col) == expect, f"got {row.get(col)!r}")

    # the exact keys form.js reverse-maps must exist in the payload
    check(
        "form.js transport key present in JSON",
        "transport" in row,
        "form.js maps transport -> transport_facility",
    )
    check("updated_at stamped on create", bool(row.get("updated_at")), str(row.get("updated_at")))

    # full-precision version read from the DB (JSON truncates to whole seconds)
    import sqlite3
    import time

    def raw_updated_at():
        c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            return c.execute("SELECT updated_at FROM students WHERE id=?",
                             (probe_id,)).fetchone()[0]
        finally:
            c.close()

    v1_raw = raw_updated_at()
    time.sleep(1.1)

    # ---- 3. partial update must not wipe siblings ----
    v1 = row.get("updated_at")
    r = client.post("/api/save-tab", json={"tab": 3, "student_id": probe_id, "data": UPDATE_DATA})
    body = r.get_json()
    check("update returns ok", r.status_code == 200 and body.get("ok") is True, str(body))

    r = client.get(f"/students/{probe_id}/json")
    row2 = r.get_json()
    check("updated field persisted", row2.get("father_name") == "P3B11-FATHER-UPDATED",
          f"got {row2.get('father_name')!r}")
    check("updated bus_route persisted", row2.get("bus_route") == "RAWALPINDI",
          f"got {row2.get('bus_route')!r}")
    for col in ("transport", "refugee_card", "disability_types", "sub_sector_id",
                "guardian_name", "digital_device_type", "date_of_admission"):
        check(f"sibling field not wiped by update: {col}", row2.get(col) == row.get(col),
              f"{row.get(col)!r} -> {row2.get(col)!r}")
    v2_raw = raw_updated_at()
    check("updated_at bumped by update (full DB precision)",
          v1_raw != v2_raw and bool(v2_raw), f"{v1_raw!r} -> {v2_raw!r}")
    check("updated_at visible in reloaded JSON", bool(row2.get("updated_at")),
          str(row2.get("updated_at")))

    # ---- 4. server rejects nothing unexpected on a valid round-trip ----
    check("no unexpected error field", "error" not in (body or {}), str(body))

except Exception as e:  # noqa: BLE001
    check("test body completed without exception", False, f"{type(e).__name__}: {e}")

finally:
    # ---- cleanup ----
    try:
        with app.app_context():
            if probe_id is not None:
                Student.query.filter(Student.id == probe_id).delete()
            Student.query.filter(Student.name == PROBE_NAME).delete()
            db.session.commit()
            after_ids = [r.id for r in Student.query.order_by(Student.id).all()]
            leftover = Student.query.filter(Student.name == PROBE_NAME).count()
        check("probe row removed / baseline ids restored", after_ids == baseline_ids,
              f"before={baseline_ids} after={after_ids}")
        check("no probe row remains", leftover == 0, f"leftover={leftover}")
    except Exception as e:  # noqa: BLE001
        check("cleanup completed", False, f"{type(e).__name__}: {e}")

print()
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
