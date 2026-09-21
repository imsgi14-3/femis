from google import genai
from google.genai import types
from pathlib import Path
import json
import os


class GeminiClient:
    """Wrapper around Google Gemini Vision API for OCR extraction."""

    def __init__(self, api_key: str = None, model: str = "gemini-3.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set. Add it to .env or pass directly.")
        self.client = genai.Client(api_key=self.api_key)
        self.model = model

    def extract_student_data(self, image_path: str) -> dict:
        """Send an image of a printed student form and extract all fields as JSON."""
        image_data = Path(image_path).read_bytes()
        ext = Path(image_path).suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")

        prompt = """You are an OCR assistant. Extract ALL student data from this printed form image.

Return ONLY a valid JSON object with these fields (use null for any field not visible or illegible):

{
  "student_name": null,
  "cnic_available": null,
  "gender": null,
  "date_of_birth": null,
  "province_of_birth": null,
  "district_of_birth": null,
  "nationality": null,
  "temp_address_type": null,
  "temp_house_no": null,
  "temp_street_no": null,
  "contact_number": null,
  "perm_city": null,
  "same_address": null,
  "perm_address_type": null,
  "perm_house_no": null,
  "perm_street_no": null,
  "religion": null,
  "mother_language": null,
  "blood_group": null,
  "email": null,
  "father_name": null,
  "father_cnic": null,
  "father_alive": null,
  "father_contact": null,
  "father_landline": null,
  "father_email": null,
  "father_qualification": null,
  "father_profession": null,
  "father_income": null,
  "father_bps": null,
  "father_domicile_province": null,
  "father_domicile_district": null,
  "mother_name": null,
  "mother_alive": null,
  "mother_cnic": null,
  "mother_contact": null,
  "mother_landline": null,
  "mother_email": null,
  "mother_qualification": null,
  "mother_profession": null,
  "mother_income": null,
  "mother_bps": null,
  "is_orphan": null,
  "orphan_type": null,
  "guardian_contact": null,
  "guardian_qualification": null,
  "guardian_profession": null,
  "guardian_income": null,
  "guardian_bps": null,
  "class": null,
  "section": null,
  "last_class_result": null,
  "admission_date": null,
  "admission_number": null,
  "last_institution_fde": null,
  "class_admitted_in": null,
  "last_institution_other": null,
  "shift": null,
  "medium_of_instruction": null,
  "years_primary": null,
  "meal_program": null,
  "mode_of_study": null,
  "total_siblings": null,
  "siblings_other_fde": null,
  "siblings_same": null,
  "siblings_private": null,
  "transport": null,
  "scholarship": null,
  "co_curricular": null,
  "scholarship_details": null,
  "achievement_details": null,
  "emergency_name": null,
  "emergency_contact": null,
  "emergency_relation": null,
  "is_refugee_idp": null,
  "idp_status": null,
  "registered_refugee": null,
  "refugee_card": null,
  "major_disability": null,
  "has_disability": null,
  "disability_cert": null,
  "disability_type": null,
  "mental_disability": null,
  "mental_disability_type": null,
  "other_conditions": null,
  "vision": null,
  "wears_glasses": null,
  "vision_difficulty": null,
  "hearing_difficulty": null,
  "hearing_aid": null,
  "difficulty_listening": null,
  "walking_difficulty": null,
  "use_crutches": null,
  "reading_writing_difficulty": null,
  "remembering_difficulty": null,
  "concentrating_difficulty": null,
  "vaccination_completed": null,
  "digital_device": null,
  "device_type": null,
  "internet_access": null
}

Rules:
- Use proper case for names (e.g., "Muhammad Ali")
- Dates should be in YYYY-MM-DD format
- For Yes/No fields, use "Yes" or "No" (capitalized)
- For gender, use exactly "Male", "Female", or "Transgender"
- For dropdown values, try to match the options listed (e.g., province names)
- If CNIC is visible, format as XXXXX-XXXXXXX-X
- If phone is visible, format as 0XXX-XXXXXXX
- Return ONLY the JSON, no extra text or explanation
"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=[
                prompt,
                types.Part.from_bytes(data=image_data, mime_type=mime_type),
            ],
        )

        raw_text = response.text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(raw_text)

    def solve_captcha(self, image_path: str) -> str:
        """Attempt to read a CAPTCHA image and return the text."""
        image_data = Path(image_path).read_bytes()
        ext = Path(image_path).suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")

        prompt = "Read the CAPTCHA text from this image. Return ONLY the characters, nothing else."

        response = self.client.models.generate_content(
            model=self.model,
            contents=[
                prompt,
                types.Part.from_bytes(data=image_data, mime_type=mime_type),
            ],
        )

        return response.text.strip()
