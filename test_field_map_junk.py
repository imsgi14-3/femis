"""_save_field_map junk blocklist (user-approved backlog #6, 2026-10-04).

Rules under test (FormFiller._junk_filter):
  * same-path in-memory copy that diverges from the curated disk entry is
    dropped (curated wins — a worker must not clobber a curator's yaml edit);
  * a new-path entry whose source_field is already covered on disk is dropped
    (cross-tab duplicate junk from inactive-pane learning);
  * among new duplicates in one batch, first-wins;
  * identical same-path re-learn passes silently; genuinely new controls and
    entries without a source_field survive.

No baseline file is modified: the end-to-end _save_field_map checks run
against a temp copy with FIELD_MAP_PATH patched, then restore it.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

import src.form_filler as ff_mod  # noqa: E402
from src.form_filler import FormFiller  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


DISK = {
    "tab_1_personal_details": {
        "identity": {
            "name": {"label": "Name", "type": "text", "source_field": "name",
                     "required": True},
            "email": {"label": "Email ID", "type": "text", "source_field": "email",
                      "required": False, "validation": "email"},
        }
    },
    "tab_3_educational_details": {
        "academics": {
            "date_of_admission": {"label": "Date of Admission", "type": "text",
                                  "source_field": "date_of_admission"},
        }
    },
}


def fresh_mem():
    return yaml.safe_load(yaml.safe_dump(DISK))


try:
    ff = FormFiller()  # real yaml load — used only as a filter host

    # ---- pure _junk_filter ------------------------------------------------
    mem = fresh_mem()
    mem["tab_1_personal_details"]["identity"]["name"]["label"] = "Stale Learned Label"
    mem["tab_3_educational_details"]["discovered_fields"] = {
        "date_of_admission": {"label": "Date of Admission", "type": "text",
                              "source_field": "date_of_admission"},
        "brand_new": {"label": "Brand New Thing", "type": "text",
                      "source_field": "brand_new_field"},
    }
    mem["tab_7_digital_access"] = {
        "digital": {
            "first_seen": {"label": "First", "type": "text",
                           "source_field": "new_source_x"},
            "second_seen": {"label": "Second", "type": "text",
                            "source_field": "new_source_x"},
        },
    }
    mem["tab_5_idps_details"] = {
        "idp_status": {"label": "IDP Status", "type": "radio", "required": True,
                       "options": ["Registered", "Un registered"]},
    }

    filtered, dropped = ff._junk_filter(mem, DISK)

    ident = filtered.get("tab_1_personal_details", {}).get("identity", {})
    check("J1 divergent same-path copy dropped (curated wins)",
          "name" not in ident and any("name" in d and "diverges" in d for d in dropped),
          str(dropped))

    df = filtered.get("tab_3_educational_details", {}).get("discovered_fields", {})
    check("J2 cross-tab dup source dropped, new sibling kept",
          "date_of_admission" not in df and "brand_new" in df,
          f"df={sorted(df)} dropped={dropped}")

    dig = filtered.get("tab_7_digital_access", {}).get("digital", {})
    check("J3 first-wins among new duplicates in one batch",
          "first_seen" in dig and "second_seen" not in dig
          and any("new_source_x" in d and "dup" in d for d in dropped),
          f"dig={sorted(dig)}")

    check("J4 identical same-path re-learn kept, not logged as divergence",
          filtered["tab_1_personal_details"]["identity"].get("email")
          == DISK["tab_1_personal_details"]["identity"]["email"]
          and not any("email" in d for d in dropped),
          str(dropped))

    check("J5 field cfg without source_field at new path kept, nothing dropped",
          "idp_status" in filtered.get("tab_5_idps_details", {})
          and len(dropped) == 3,
          f"dropped={dropped}")

    clean, clean_dropped = ff._junk_filter(fresh_mem(), DISK)
    check("J6 clean memory identical to disk: no drops", clean == DISK
          and not clean_dropped, str(clean_dropped))

    # ---- end-to-end _save_field_map (temp FIELD_MAP_PATH) -----------------
    tmpdir = Path(tempfile.mkdtemp(prefix="femis_junk_"))
    disk_path = tmpdir / "field_mapping.yaml"
    disk_path.write_text(yaml.safe_dump(DISK, sort_keys=False), encoding="utf-8")
    orig_path = ff_mod.FIELD_MAP_PATH
    ff_mod.FIELD_MAP_PATH = disk_path
    try:
        w = FormFiller()  # loads the temp disk copy
        w.field_map = fresh_mem()
        w.field_map["tab_1_personal_details"]["identity"]["name"]["label"] = "Clobber Attempt"
        w.field_map["tab_3_educational_details"]["discovered_fields"] = {
            "date_of_admission": {"label": "Date of Admission", "type": "text",
                                  "source_field": "date_of_admission"},
            "brand_new": {"label": "Brand New Thing", "type": "text",
                          "source_field": "brand_new_field"},
        }
        w._save_field_map()
        on_disk = yaml.safe_load(disk_path.read_text(encoding="utf-8"))

        check("J7 e2e curated entries survive byte-identical",
              on_disk["tab_1_personal_details"]["identity"]["name"] == DISK["tab_1_personal_details"]["identity"]["name"]
              and on_disk["tab_3_educational_details"]["academics"]["date_of_admission"]
              == DISK["tab_3_educational_details"]["academics"]["date_of_admission"],
              str(on_disk["tab_1_personal_details"]["identity"]["name"]))

        jdf = on_disk.get("tab_3_educational_details", {}).get("discovered_fields", {})
        check("J8 e2e dup source never written, new control written",
              "date_of_admission" not in jdf
              and jdf.get("brand_new", {}).get("source_field") == "brand_new_field",
              f"jdf={sorted(jdf)}")

        check("J9 e2e in-memory map mirrors merged disk", w.field_map == on_disk, "")

        check("J10 e2e tmp file cleaned up",
              not (tmpdir / "field_mapping.yaml.tmp").exists(), "")
    finally:
        ff_mod.FIELD_MAP_PATH = orig_path
        shutil.rmtree(tmpdir, ignore_errors=True)
finally:
    passed = sum(1 for _, ok in results if ok)
    print("=" * 60)
    print(f"{passed}/{len(results)} checks passed")
    print("=" * 60)
    sys.exit(0 if passed == len(results) else 1)
