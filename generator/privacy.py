"""Scrubbing personal data out of free text before it is committed.

Profiles and resume specs are committed, and free text copied from GitHub -
README excerpts, repo descriptions, commit messages - can carry an email address
or phone number. Logins are handled separately by the caller: they are kept in
profiles on purpose, and replaced in anything printed on a resume.
"""
from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Candidate phone numbers; confirmed by digit count below so dates and version
# strings ("2024-01-15", "v1.2.3") survive.
# Bounded by non-digits only: a number ending a sentence ("...555-0142.") must match.
PHONE = re.compile(r"(?<!\d)\+?\(?\d[\d\s().-]{7,}\d(?!\d)")
DATE_LIKE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")
MIN_PHONE_DIGITS = 9


def _phone(match: re.Match[str]) -> str:
    text = match.group(0)
    digits = sum(ch.isdigit() for ch in text)
    if digits < MIN_PHONE_DIGITS or DATE_LIKE.match(text.strip("+( ")):
        return text
    return "[phone]"


def scrub(text: str | None) -> str | None:
    """Replace email addresses and phone numbers."""
    if not text:
        return text
    text = EMAIL.sub("[email]", text)
    return PHONE.sub(_phone, text)


def replace_login(text: str, login: str, replacement: str) -> str:
    """Case-insensitive replacement of a login inside resume text."""
    if not login:
        return text
    return re.sub(re.escape(login), replacement, text, flags=re.IGNORECASE)
