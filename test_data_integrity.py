"""Phase 2 regression: Tab 7 persistence + transport/refugee/disability round trips."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "femis-web"))
sys.path.insert(0, str(ROOT))

from app import app, db, Student, FORM_FIELD_MAP  # noqa: E402
from form_payloads import create_full  # noqa: E402
from src.data_sources.webform_handler import WebFormHandler  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


with app.app_context():
    client = app.test_client()
    with client.session_transaction() as s:
        s["role"] = "admin"
    created_ids = []

    # --- create student (complete: every tab filled, server mandatory twin) ---
    resp_st, body = create_full(client, name="PHASE TWO DATA INTEGRITY")
    sid = body.get("student_id") if body else None
    check("create student ok", resp_st == 200 and body.get("ok") and sid is not None, json.dumps(body))
    if sid:
        created_ids.append(sid)

    # --- Issue 2: transport_facility -> DB transport ---
    resp = client.post(
        "/api/save-tab",
        json={
            "tab": 3,
            "student_id": sid,
            "data": {"transport_facility": "Institution Bus", "bus_route": "URBAN-I"},
        },
    )
    j = client.get(f"/students/{sid}/json").get_json()
    check(
        "transport_facility persisted to DB transport",
        j.get("transport") == "Institution Bus",
        str(j.get("transport")),
    )

    # --- Issue 3: refugee_card_number -> DB refugee_card ---
    resp = client.post(
        "/api/save-tab",
        json={
            "tab": 5,
            "student_id": sid,
            "data": {
                "is_refugee": "1",
                "is_registered_refugee": "1",
                "idp_status_id": "1",
                "refugee_card_number": "REF-998877",
            },
        },
    )
    j = client.get(f"/students/{sid}/json").get_json()
    check(
        "refugee_card_number persisted to DB refugee_card",
        j.get("refugee_card") == "REF-998877",
        str(j.get("refugee_card")),
    )

    # --- Issue 4: disability_types[] multi-value -> DB disability_types ---
    resp = client.post(
        "/api/save-tab",
        json={
            "tab": 6,
            "student_id": sid,
            "data": {"has_major_disability": "1", "disability_types[]": "Visual,Hearing"},
        },
    )
    j = client.get(f"/students/{sid}/json").get_json()
    check(
        "disability_types[] persisted to DB disability_types",
        j.get("disability_types") == "Visual,Hearing",
        str(j.get("disability_types")),
    )

    # --- Issue 1: Tab 7 data via final-submit (save/final-submit cycle) ---
    resp = client.post(
        "/api/final-submit",
        json={
            "student_id": sid,
            "data": {
                "digital_device_at_home": "1",
                "digital_device_type[]": "Mobile,Television",
                "internet_at_home": "0",
            },
        },
    )
    body = resp.get_json()
    check("final-submit with data ok", resp.status_code == 200 and body.get("ok"), json.dumps(body))
    j = client.get(f"/students/{sid}/json").get_json()
    check(
        "tab7 digital_device_at_home persisted",
        j.get("digital_device_at_home") == "1",
        str(j.get("digital_device_at_home")),
    )
    check(
        "tab7 digital_device_type[] persisted",
        j.get("digital_device_type") == "Mobile,Television",
        str(j.get("digital_device_type")),
    )
    check(
        "tab7 internet_at_home persisted",
        j.get("internet_at_home") == "0",
        str(j.get("internet_at_home")),
    )
    check("tab7 submitted flag True", j.get("submitted") in (True, 1), str(j.get("submitted")))

    # --- bot read path: portal -> DB -> WebFormHandler round trip ---
    rec = WebFormHandler().read_by_id(sid) if sid else None
    check(
        "bot reads transport_facility (aliased from transport)",
        bool(rec) and rec.get("transport_facility") == "Institution Bus",
        str(rec.get("transport_facility") if rec else None),
    )
    check(
        "bot reads refugee_card",
        bool(rec) and rec.get("refugee_card") == "REF-998877",
        str(rec.get("refugee_card") if rec else None),
    )
    check(
        "bot reads disability_types",
        bool(rec) and rec.get("disability_types") == "Visual,Hearing",
        str(rec.get("disability_types") if rec else None),
    )
    check(
        "bot reads tab7 digital_device_at_home",
        bool(rec) and rec.get("digital_device_at_home") == "1",
        str(rec.get("digital_device_at_home") if rec else None),
    )

    # --- legacy final-submit without data still works (complete record) ---
    resp_st, body = create_full(client, name="PHASE TWO LEGACY FINAL")
    sid2 = body.get("student_id")
    if sid2:
        created_ids.append(sid2)
    resp = client.post("/api/final-submit", json={"student_id": sid2})
    body = resp.get_json()
    check("legacy final-submit (no data) ok", bool(body and body.get("ok")), json.dumps(body))
    j2 = client.get(f"/students/{sid2}/json").get_json()
    check("legacy final-submit sets submitted", j2.get("submitted") in (True, 1), str(j2.get("submitted")))

    # --- mapping / model static checks ---
    check(
        "FORM_FIELD_MAP transport_facility -> transport",
        FORM_FIELD_MAP.get("transport_facility") == "transport",
    )
    check(
        "FORM_FIELD_MAP refugee_card_number -> refugee_card",
        FORM_FIELD_MAP.get("refugee_card_number") == "refugee_card",
    )
    check(
        "FORM_FIELD_MAP disability_types[] -> disability_types",
        FORM_FIELD_MAP.get("disability_types[]") == "disability_types",
    )
    check(
        "Student model has transport column",
        hasattr(Student, "transport") and "transport" in Student.__table__.columns,
    )

    # --- cleanup created rows (never touch existing students) ---
    for i in created_ids:
        st = db.session.get(Student, i)
        if st:
            db.session.delete(st)
    db.session.commit()
    check("cleanup test students", True)

# --- form.js static checks ---
js = (ROOT / "femis-web" / "static" / "form.js").read_text(encoding="utf-8")
check(
    "form.js final-submit payload includes data (both branches)",
    js.count("data: data") >= 2,
    f"count={js.count('data: data')}",
)
check(
    "form.js generic [] multi-checkbox collection",
    "slice(-2)" in js and "arrayChecks" in js and "deviceChecked" not in js,
)
check(
    "form.js reverseMap refugee_card -> refugee_card_number",
    '"refugee_card": "refugee_card_number"' in js,
)
check(
    "form.js reverseMap transport -> transport_facility",
    '"transport": "transport_facility"' in js,
)

failed = [r for r in results if not r[1]]
print(f"\n{'='*40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
