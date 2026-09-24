"""Local CAPTCHA OCR stub — returns empty so manual file-poll flow is used."""
from __future__ import annotations


def solve_local(image_path: str) -> str:
    """Best-effort local OCR. Returns '' when unavailable (use manual captcha)."""
    return ""
