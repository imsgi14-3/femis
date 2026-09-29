"""Complete per-tab PA-form payloads for tests (not collected: no test_ prefix).

Server-side mandatory validation (femis-web/mandatory.py) rejects a save of
tab N unless every visible mandatory field of tab N is empty-free, and a
final-submit unless every tab is — so any test that creates records through
/api/save-tab or the legacy /submit route must post complete payloads.

Conventions:
- Keys are FORM field names; app.py maps them through FORM_FIELD_MAP
  (present_address -> present_address_other, transport_facility -> transport,
  ...).  Fields not listed there pass through unchanged.
- Option values are not validated server-side — only emptiness matters — but
  the values below mirror the real form so branch rules behave realistically
  (address_type=Sector, father/mother alive, profession=Business, ...).
- Defaults are unique per call (b_form 13 digits, admission_number ADM-...),
  so independent creates never trip the 409 uniqueness gate; override to test
  collisions.
- `over` passed to create_full() is applied to EVERY tab payload so a
  suite-specific class_id / roll_no / name sticks through the progressive
  saves (a later tab's default must not clobber it).
"""
import uuid


def _bform():
    return "35202-%07d-%d" % (uuid.uuid4().int % 10_000_000,
                              uuid.uuid4().int % 10)


def _adm():
    return "ADM-" + uuid.uuid4().hex[:8].upper()


def tab1(**over):
    """Tab 1 — personal + address family (Sector branch, male, b-form)."""
    base = {
        "name": "Payload Student",
        "is_bform_available": "1",
        "b_form": _bform(),
        "gender": "Male",
        "date_of_birth": "01/15/2015",
        "birth_province_id": "1",
        "birth_district_id": "1",
        "nationality": "Pakistani",
        "address_type": "Sector",
        "sector_id": "1",
        "sub_sector_id": "1",
        "house": "House 1",
        "street": "Street 1",
        "contact_number": "0300-1234567",
        "city_id": "1",
        "present_address_type": "Sector",
        "present_sector_id": "1",
        "present_sub_sector_id": "1",
        "present_house": "House 1",
        "present_street": "Street 1",
        "religion": "Islam",
        "language_id": "1",
        "email": "payload@example.com",
    }
    base.update(over)
    return base


def tab2(**over):
    """Tab 2 — both parents alive, father Business, mother Housewife."""
    base = {
        "father_name": "FATHER PAYLOAD",
        "father_cnic": "35202-1234567-3",
        "is_father_alive": "1",
        "father_contact": "0300-1234568",
        "father_qualification": "Matric",
        "father_profession": "Business",
        "father_monthly_income": "Less than 50,000",
        "mother_name": "MOTHER PAYLOAD",
        "is_mother_alive": "1",
        "mother_contact": "0300-1234569",
        "mother_profession": "Housewife",
        "mother_qualification": "Matric",
        "is_orphan": "0",
    }
    base.update(over)
    return base


def tab3(**over):
    """Tab 3 — academics (no scholarship/co-curricular, walking to school)."""
    base = {
        "class_id": "9",
        "section_id": "A",
        "date_of_admission": "01/15/2015",
        "class_admitted_id": "8",
        "medium_of_instruction": "English",
        "mode_of_study": "Day Scholar",
        "admission_number": _adm(),
        "shift": "Morning",
        "total_siblings": "1",
        "school_meal_program_availing": "0",
        "transport_facility": "Walking",
        "scholarship": "0",
        "cocurricular_activities": "0",
    }
    base.update(over)
    return base


def tab4(**over):
    base = {
        "emergency_name": "EMERGENCY PAYLOAD",
        "emergency_contact": "0300-1234570",
        "emergency_relation": "Father",
    }
    base.update(over)
    return base


def tab5(**over):
    base = {"is_refugee": "0"}
    base.update(over)
    return base


def tab6(**over):
    base = {
        "has_major_disability": "0",
        "has_mental_disability": "0",
        "visually_fit": "1",
        "uses_glasses": "0",
        "has_hearing_difficulties": "0",
        "difficulty_listening": "0",
        "difficulty_walking": "0",
        "uses_crutches_walker": "0",
        "uses_hearing_aid": "0",
        "difficulty_seeing_board": "0",
        "difficulty_reading_writing": "0",
        "difficulty_remembering": "0",
        "difficulty_concentrating": "0",
    }
    base.update(over)
    return base


def tab7(**over):
    base = {"digital_device_at_home": "0", "internet_at_home": "1"}
    base.update(over)
    return base


def form_all(**over):
    """One flat payload carrying every tab — for the legacy /submit route,
    which has no tab notion and validates the assembled record at once.
    Fresh unique defaults on every call."""
    base = {}
    for make in (tab1, tab2, tab3, tab4, tab5, tab6, tab7):
        base.update(make())
    base.update(over)
    return base


def create_full(client, **over):
    """Progressive save of tabs 1..7; returns (status, body) of the last save.

    `client` must be allowed to modify the record (admin) — the create
    branch itself needs no session, but tabs 2..7 are updates.
    `over` (name, roll_no, class_id, section_id, b_form, ...) is applied to
    every tab so later defaults never clobber a suite-specific value.
    """
    sid = None
    st, body = 500, {}
    for tab, make in ((1, tab1), (2, tab2), (3, tab3), (4, tab4),
                      (5, tab5), (6, tab6), (7, tab7)):
        data = make(**over)
        r = client.post("/api/save-tab",
                        json={"tab": tab, "student_id": sid, "data": data})
        st = r.status_code
        body = r.get_json() or {}
        if not body.get("ok"):
            return st, body
        sid = body.get("student_id")
    return st, body
