import re


def validate_cnic(value: str) -> bool:
    """Validate Pakistani CNIC format: 35202-1234567-1"""
    pattern = r"^[1-9]\d{4}-\d{7}-\d{1}$"
    return bool(re.match(pattern, value))


def validate_mobile(value: str) -> bool:
    """Validate Pakistani mobile format: 03XX-XXXXXXX"""
    pattern = r"^03\d{2}-\d{7}$"
    return bool(re.match(pattern, value))


def validate_landline(value: str) -> bool:
    """Validate Pakistani landline format: 051-1234567"""
    pattern = r"^05\d{1}-\d{7}$"
    return bool(re.match(pattern, value))


def validate_email(value: str) -> bool:
    """Basic email validation."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, value))


def validate_date(value: str) -> bool:
    """Validate date in YYYY-MM-DD format."""
    try:
        from datetime import datetime
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


VALIDATORS = {
    "cnic": validate_cnic,
    "mobile_pakistani": validate_mobile,
    "landline": validate_landline,
    "email": validate_email,
    "date": validate_date,
}


def validate_field(value: str, validation_type: str) -> bool:
    """Validate a field value against its validation type."""
    if not value or not validation_type:
        return True
    validator = VALIDATORS.get(validation_type)
    if validator:
        return validator(str(value))
    return True


def format_cnic(raw: str) -> str:
    """Convert raw digits to CNIC format: 35202-1234567-1"""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 13:
        return f"{digits[:5]}-{digits[5:12]}-{digits[12]}"
    return raw


def format_mobile(raw: str) -> str:
    """Convert raw digits to mobile format: 03XX-XXXXXXX"""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("03"):
        return f"{digits[:4]}-{digits[4:]}"
    return raw
