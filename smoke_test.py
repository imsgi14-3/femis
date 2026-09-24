"""Smoke test: save-tab persists sub_sector fields; same-address autofill works."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "femis-web"))

from app import app, db, Student  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


with app.app_context():
    # --- 1. save-tab persists sub_sector_id / present_sub_sector_id ---
    client = app.test_client()
    payload = {
        "tab": 1,
        "student_id": None,
        "data": {
            "name": "SMOKE TEST STUDENT",
            "address_type": "Sector",
            "sector_id": "F-6",
            "sub_sector_id": "F-6/1",
            "house": "12",
            "street": "3",
            "present_address_type": "Sector",
            "present_sector_id": "F-6",
            "present_sub_sector_id": "F-6/1",
            "present_house": "12",
            "present_street": "3",
            "same_as_permanent_address": "1",
        },
    }
    resp = client.post("/api/save-tab", json=payload)
    body = resp.get_json()
    check("save-tab returns 200", resp.status_code == 200, str(resp.status_code))
    check("save-tab ok=True", body and body.get("ok"), json.dumps(body))
    sid = body.get("student_id") if body else None
    check("student_id returned", sid is not None)

    if sid:
        student = Student.query.get(sid)
        check("sub_sector_id persisted", student.sub_sector_id == "F-6/1", student.sub_sector_id)
        check(
            "present_sub_sector_id persisted",
            student.present_sub_sector_id == "F-6/1",
            student.present_sub_sector_id,
        )
        check("same_address persisted", student.same_address == "1", student.same_address)
        check("sector_id persisted", student.sector_id == "F-6", student.sector_id)

        # student JSON endpoint exposes new fields
        resp2 = client.get(f"/students/{sid}/json")
        j = resp2.get_json()
        check(
            "student JSON has sub_sector_id",
            j.get("sub_sector_id") == "F-6/1" if j else False,
            str(j.get("sub_sector_id") if j else None),
        )
        check(
            "student JSON has present_sub_sector_id",
            j.get("present_sub_sector_id") == "F-6/1" if j else False,
            str(j.get("present_sub_sector_id") if j else None),
        )

        # cleanup test row
        db.session.delete(student)
        db.session.commit()
        check("cleanup test student", True)

# --- 2. form.js contains same-address autofill pairs ---
js = (Path(__file__).parent / "femis-web" / "static" / "form.js").read_text(encoding="utf-8")
check(
    "form.js has same-address autofill",
    "copyAddresses" in js and '"sub_sector_id", "present_sub_sector_id"' in js,
)
check(
    "form.js requires FEMIS mandatory fields (qualification, income, guardian)",
    '"father_qualification"' in js.split("mandatoryByTab")[1].split("};")[0]
    and '"guardian_name"' in js.split("mandatoryByTab")[1].split("};")[0]
    and '"father_monthly_income"' in js.split("mandatoryByTab")[1].split("};")[0],
)
check(
    "form.js removes primary_education from mandatory",
    "primary_education_completion_years" not in js.split("mandatoryByTab")[1].split("};")[0],
)

# --- 3. field_mapping labels match portal form.html ---
import yaml  # noqa: E402
import re  # noqa: E402

fm = yaml.safe_load(
    (Path(__file__).parent / "config" / "field_mapping.yaml").read_text(encoding="utf-8")
)
html = (Path(__file__).parent / "femis-web" / "templates" / "form.html").read_text(
    encoding="utf-8"
)
portal_labels = set()
for m in re.finditer(r'<label[^>]*>(.*?)</label>', html, re.DOTALL):
    clean = re.sub(r"<[^>]+>", "", m.group(1)).replace("*", "").strip()
    if clean:
        portal_labels.add(clean)

mapped_labels = set()


def walk(obj):
    if isinstance(obj, dict):
        # Skip portal auto-discovered fields (not in local form.html)
        note = str(obj.get("note") or "")
        label = obj.get("label")
        if (
            "label" in obj
            and isinstance(label, str)
            and "Auto-discovered from portal" not in note
            and not re.fullmatch(r"[a-z0-9_]+", label)
        ):
            mapped_labels.add(label)
        for v in obj.values():
            walk(v)
    elif isinstance(obj, list):
        for v in obj:
            walk(v)


walk(fm)
# Portal-only labels intentionally not in local form.html
PORTAL_ONLY_LABELS = {"Visually fit / 6X6"}
missing = sorted(mapped_labels - portal_labels - PORTAL_ONLY_LABELS)
check(
    "all field_mapping labels exist in portal form",
    not missing,
    f"missing: {missing}" if missing else f"{len(mapped_labels)} labels OK",
)

# --- 4. date normalizer regression ---
sys.path.insert(0, str(Path(__file__).parent))
from src.form_filler import FormFiller  # noqa: E402

ff = FormFiller()
check("date 15/03/2010 -> 2010-03-15", ff._normalize_date("15/03/2010") == "2010-03-15")
check("date 2010-03-15 unchanged", ff._normalize_date("2010-03-15") == "2010-03-15")
check("date 15/03/10 -> 2010-03-15", ff._normalize_date("15/03/10") == "2010-03-15")

failed = [r for r in results if not r[1]]
print(f"\n{'='*40}\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
