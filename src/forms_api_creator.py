"""Google Forms API Creator — Auto-creates a Google Form from the FEMIS field mapping.

Prerequisites:
1. Enable Google Forms API in Google Cloud Console
2. Create a service account and download credentials JSON
3. Set GOOGLE_SHEETS_CREDENTIALS in .env to the credentials file path

Usage:
    python -m src.forms_api_creator
"""
import json
import yaml
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from src.utils.logger import setup_logger
from dotenv import load_dotenv
import os

load_dotenv()
logger = setup_logger("forms_api_creator")

FIELD_MAP_PATH = Path(__file__).parent.parent / "config" / "field_mapping.yaml"
FORM_TYPE_MAP = {
    "text": "SHORT_ANSWER",
    "dropdown": "MULTIPLE_CHOICE",
    "radio": "MULTIPLE_CHOICE",
    "date": "SHORT_ANSWER",
    "checkbox": "CHECKBOX",
}

SECTION_TITLES = {
    "tab_1_personal_details": "Personal Details",
    "tab_2_parents_guardian": "Parents / Guardian Information",
    "tab_3_educational_details": "Educational Details",
    "tab_4_emergency_contact": "Emergency Contact",
    "tab_5_idps_details": "IDPs Details",
    "tab_6_health_details": "Health Details",
    "tab_7_digital_access": "Digital Access",
}

SCOPES = ["https://www.googleapis.com/auth/forms.body"]


def get_credentials():
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_path:
        raise ValueError("Set GOOGLE_SHEETS_CREDENTIALS in .env to your service account JSON path")
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return creds


def load_field_map() -> dict:
    with open(FIELD_MAP_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_form_requests(field_map: dict) -> list[dict]:
    """Build the list of requests to create the form structure."""
    requests = []
    section_ids = {}

    for tab_key, section_title in SECTION_TITLES.items():
        if tab_key not in field_map:
            continue

        tab_data = field_map[tab_key]
        if isinstance(tab_data, dict) and tab_data.get("status") == "PENDING_PHASE_2":
            continue

        # Create section (except first one — it's implicit)
        if section_title != "Personal Details":
            section_id = f"section_{len(section_ids)}"
            section_ids[section_title] = section_id
            requests.append({
                "createItem": {
                    "item": {
                        "title": section_title,
                        "pageBreakItem": {},
                    },
                    "location": {"index": len(requests)},
                }
            })

        # Extract fields
        fields = _extract_fields(tab_data)
        for field in fields:
            question = _build_question_item(field)
            if question:
                requests.append({
                    "createItem": {
                        "item": question,
                        "location": {"index": len(requests)},
                    }
                })

    return requests


def _extract_fields(tab_data: dict) -> list[dict]:
    """Extract fields from both nested and flat structures."""
    fields = []
    for group_name, group_fields in tab_data.items():
        if not isinstance(group_fields, dict):
            continue

        has_nested = any(isinstance(v, dict) and "label" in v for v in group_fields.values())

        if has_nested:
            for field_name, field_config in group_fields.items():
                if isinstance(field_config, dict) and "label" in field_config:
                    fields.append(field_config)
        elif "label" in group_fields:
            fields.append(group_fields)

    return fields


def _build_question_item(field_config: dict) -> dict | None:
    """Build a Google Forms question item from field config."""
    field_type = field_config.get("type", "text")
    label = field_config["label"]
    required = field_config.get("required", False)
    form_type = FORM_TYPE_MAP.get(field_type, "SHORT_ANSWER")

    item = {
        "title": label,
        "required": required,
    }

    if form_type == "SHORT_ANSWER":
        item["questionItem"] = {
            "question": {
                "required": required,
                "textQuestion": {},
            }
        }
        validation = field_config.get("validation")
        if validation:
            item["questionItem"]["question"]["textQuestion"]["paragraph"] = False
    elif form_type == "MULTIPLE_CHOICE":
        options = field_config.get("options", [])
        item["questionItem"] = {
            "question": {
                "required": required,
                "choiceQuestion": {
                    "type": "RADIO" if field_type == "radio" else "DROPDOWN",
                    "options": [{"value": opt} for opt in options],
                },
            }
        }
    elif form_type == "CHECKBOX":
        options = field_config.get("options", ["Yes"])
        item["questionItem"] = {
            "question": {
                "required": required,
                "choiceQuestion": {
                    "type": "CHECKBOX",
                    "options": [{"value": opt} for opt in options],
                },
            }
        }

    return item


def create_form():
    """Create the Google Form via API."""
    creds = get_credentials()
    service = build("forms", "v1", credentials=creds)

    # Step 1: Create empty form
    form_body = {
        "info": {
            "title": "FDE Student Admission Form",
            "documentTitle": "FDE Student Admission Form",
        }
    }
    logger.info("Creating form...")
    form = service.forms().create(body=form_body).execute()
    form_id = form["formId"]
    form_url = form.get("responderUri", f"https://docs.google.com/forms/d/{form_id}/edit")
    logger.info(f"Form created: {form_url}")

    # Step 2: Add all questions
    field_map = load_field_map()
    requests = build_form_requests(field_map)
    logger.info(f"Adding {len(requests)} items...")

    # Batch requests (max 100 per batch)
    batch_size = 100
    for i in range(0, len(requests), batch_size):
        batch = requests[i:i + batch_size]
        service.forms().batchUpdate(
            formId=form_id,
            body={"requests": batch},
        ).execute()
        logger.info(f"  Added batch {i // batch_size + 1} ({len(batch)} items)")

    print(f"\n{'='*60}")
    print(f"Google Form Created Successfully!")
    print(f"{'='*60}")
    print(f"Form ID:  {form_id}")
    print(f"Edit URL: {form_url}")
    print(f"Fill URL: https://docs.google.com/forms/d/{form_id}/viewform")
    print(f"{'='*60}")
    print(f"\nQuestions added: {len(requests)}")
    print(f"\nShare the Fill URL with parents/teachers to collect student data.")
    print(f"Responses will be in the linked Google Sheet.")

    return form_id, form_url


if __name__ == "__main__":
    create_form()
