"""Google Form Generator — creates a Google Form matching the FEMIS student fields.

This uses the Google Forms API via a service account.
Alternatively, generates a form structure that can be manually created.
"""
import json
import yaml
from pathlib import Path
from src.utils.logger import setup_logger

logger = setup_logger("google_form_generator")

FIELD_MAP_PATH = Path(__file__).parent.parent / "config" / "field_mapping.yaml"

# Fields mapped to Google Forms question types
FORM_TYPE_MAP = {
    "text": "SHORT_ANSWER",
    "dropdown": "MULTIPLE_CHOICE",
    "radio": "MULTIPLE_CHOICE",
    "date": "SHORT_ANSWER",
    "checkbox": "CHECKBOX",
}

# Section titles for each tab
SECTION_TITLES = {
    "tab_1_personal_details": "Personal Details",
    "tab_2_parents_guardian": "Parents / Guardian Information",
    "tab_3_educational_details": "Educational Details",
    "tab_4_emergency_contact": "Emergency Contact",
    "tab_5_idps_details": "IDPs Details",
    "tab_6_health_details": "Health Details",
    "tab_7_digital_access": "Digital Access",
}


def generate_form_json(output_path: str = "data/output/femis_form.json"):
    """Generate a JSON structure that can be used with Google Forms API or imported."""
    with open(FIELD_MAP_PATH, "r", encoding="utf-8") as f:
        field_map = yaml.safe_load(f)

    form_structure = {
        "formInfo": {
            "title": "FDE Student Admission Form",
            "description": "Federal Directorate of Education — Student data collection form. Please fill all required fields accurately.",
        },
        "sections": [],
    }

    for tab_key, section_title in SECTION_TITLES.items():
        if tab_key not in field_map:
            continue

        tab_data = field_map[tab_key]
        if isinstance(tab_data, dict) and tab_data.get("status") == "PENDING_PHASE_2":
            continue

        section = {
            "title": section_title,
            "questions": [],
        }

        for group_name, group_fields in tab_data.items():
            if not isinstance(group_fields, dict):
                continue

            # Nested structure: group -> field -> config (tabs 1-3)
            has_nested_fields = any(
                isinstance(v, dict) and "label" in v
                for v in group_fields.values()
            )

            if has_nested_fields:
                for field_name, field_config in group_fields.items():
                    if isinstance(field_config, dict) and "label" in field_config:
                        question = _build_question(field_config)
                        section["questions"].append(question)
            # Flat structure: field -> config directly (tabs 4-7)
            elif "label" in group_fields:
                question = _build_question(group_fields)
                section["questions"].append(question)

        if section["questions"]:
            form_structure["sections"].append(section)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(form_structure, f, indent=2, ensure_ascii=False)

    logger.info(f"Form structure saved to: {output_path}")
    _print_summary(form_structure)
    return form_structure


def _build_question(field_config: dict) -> dict:
    """Convert a field config into a Google Forms question object."""
    field_type = field_config.get("type", "text")
    question = {
        "title": field_config["label"],
        "required": field_config.get("required", False),
        "type": FORM_TYPE_MAP.get(field_type, "SHORT_ANSWER"),
    }

    if field_type in ("dropdown", "radio"):
        options = field_config.get("options", [])
        question["options"] = [{"value": opt} for opt in options]

    if field_type == "checkbox":
        options = field_config.get("options", ["Yes"])
        question["options"] = [{"value": opt} for opt in options]

    if field_type == "date":
        question["helpText"] = "Format: YYYY-MM-DD"

    validation = field_config.get("validation")
    if validation:
        if validation == "cnic":
            question["helpText"] = "Format: XXXXX-XXXXXXX-X (13 digits)"
        elif validation == "mobile_pakistani":
            question["helpText"] = "Format: 0XXX-XXXXXXX"
        elif validation == "email":
            question["helpText"] = "Valid email address"

    return question


def _print_summary(form_structure: dict):
    """Print a summary of the generated form."""
    total_questions = sum(len(s["questions"]) for s in form_structure["sections"])
    print(f"\n{'='*50}")
    print(f"Google Form Structure Generated")
    print(f"{'='*50}")
    print(f"Title: {form_structure['formInfo']['title']}")
    print(f"Sections: {len(form_structure['sections'])}")
    print(f"Total Questions: {total_questions}")
    print(f"\nSections:")
    for i, section in enumerate(form_structure["sections"], 1):
        print(f"  {i}. {section['title']} ({len(section['questions'])} questions)")
    print(f"{'='*50}")


if __name__ == "__main__":
    generate_form_json()
