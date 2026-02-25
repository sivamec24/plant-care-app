"""
Input validation and normalization.

Trims and bounds field lengths, filters suspicious characters while allowing
natural punctuation, normalizes select values, and builds a clean payload for
downstream processing.
"""

from __future__ import annotations
import html
import re
from typing import Any, Dict, Tuple

# Allowlist regex: we REMOVE anything NOT in this set.
# Includes letters/numbers/space and common lightweight punctuation used in names.
# This keeps plant/city fields readable while dropping odd control/symbol characters.

_SAFE_CHARS_PATTERN = re.compile(r"[^a-zA-Z0-9\s\-\.,'()/&]+")

# UUID validation pattern (RFC 4122 compliant)
_UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)

MAX_PLANT_LEN = 80
MAX_CITY_LEN = 80
MAX_QUESTION_LEN = 1200

# Allowed values for the care-context select. Anything else is coerced to the default.
# Import from constants to ensure consistency across the app
try:
    from app.constants import PLANT_LOCATIONS
    CARE_CONTEXT_CHOICES = {loc[0] for loc in PLANT_LOCATIONS}
except ImportError:
    # Fallback for tests or if constants module doesn't exist
    CARE_CONTEXT_CHOICES = {"indoor_potted", "outdoor_potted", "outdoor_bed", "greenhouse", "office"}


def _soft_sanitize(text: str, max_len: int) -> str:
    """
    Normalizes names/locations:
    - strip whitespace
    - bound length
    - remove dangerous HTML event handlers and keywords
    - remove disallowed characters via allowlist
    - collapse double spaces
    """
    t = (text or "").strip()
    if not t:
        return ""
    t = t[:max_len]

    # Remove HTML event handlers and dangerous keywords (XSS protection)
    dangerous_keywords = [
        'onerror', 'onload', 'onclick', 'onmouseover', 'onmouseout',
        'onmousemove', 'onmousedown', 'onmouseup', 'onfocus', 'onblur',
        'onchange', 'onsubmit', 'javascript:', 'data:', 'vbscript:'
    ]
    for keyword in dangerous_keywords:
        t = re.sub(keyword, '', t, flags=re.IGNORECASE)

    # Remove disallowed characters via allowlist
    t = _SAFE_CHARS_PATTERN.sub("", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t


def _soft_sanitize_question(text: str, max_len: int) -> str:
    """
    Question field is a bit more permissive:
    - strip & bound length
    - remove control chars only; keep reasonable punctuation
    - normalize repeated tabs/spaces
    """
    t = (text or "").strip()
    if not t:
        return ""
    t = t[:max_len]
    t = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t


def normalize_context(value: str | None) -> str:
    """Coerce unknown/missing values to the default option."""
    v = (value or "").strip().lower()
    return v if v in CARE_CONTEXT_CHOICES else "indoor_potted"


def display_sanitize_short(text: str) -> str:
    """
    Short UI messages are HTML-escaped and truncated to avoid layout breaks.
    Use this only for brief notices surfaced to the page.
    """
    if not text:
        return ""
    t = html.escape(text)
    return (t[:240] + "…") if len(t) > 240 else t


def validate_inputs(form: Dict[str, Any]) -> Tuple[Dict[str, Any], str | None]:
    """
    Validates incoming form data and returns (payload, error_message).
    On success, payload has:
      - plant (optional sanitized string)
      - city (optional sanitized string)
      - care_context (normalized select value)
      - question (required string within length limit)
    """
    raw_plant = form.get("plant", "")
    raw_city = form.get("city", "")
    raw_question = form.get("question", "")
    raw_context = form.get("care_context", "")

    plant = _soft_sanitize(raw_plant, MAX_PLANT_LEN)
    city = _soft_sanitize(raw_city, MAX_CITY_LEN)
    question = _soft_sanitize_question(raw_question, MAX_QUESTION_LEN)
    care_context = normalize_context(raw_context)

    if not question:
        return {}, "Question is required and must be under 1200 characters."

    return {
        "plant": plant,
        "city": city,
        "question": question,
        "care_context": care_context,
    }, None


def safe_referrer_or(fallback: str) -> str:
    """Return request.referrer if it points back to this app, otherwise fallback.

    Prevents open redirect attacks by validating that the referrer is a
    same-origin, path-only URL matching allowed prefixes.  Reuses the
    ``ALLOWED_REDIRECT_PREFIXES`` whitelist from ``app.routes.auth``.
    """
    from flask import request
    from urllib.parse import urlparse

    referrer = request.referrer
    if not referrer:
        return fallback

    parsed = urlparse(referrer)

    # If the referrer has a host, it must match the current request host
    if parsed.netloc and parsed.netloc != request.host:
        return fallback

    path = parsed.path or ""

    # Must start with / but not // (protocol-relative)
    if not path.startswith("/") or path.startswith("//"):
        return fallback

    # Must match one of the allowed prefixes (same whitelist as auth.py)
    from app.routes.auth import ALLOWED_REDIRECT_PREFIXES
    if not any(path.startswith(prefix) for prefix in ALLOWED_REDIRECT_PREFIXES):
        return fallback

    return referrer


def is_valid_uuid(value: str | None) -> bool:
    """
    Check if a string is a valid UUID (RFC 4122 format).

    Args:
        value: String to validate

    Returns:
        True if valid UUID format, False otherwise

    Example:
        >>> is_valid_uuid("550e8400-e29b-41d4-a716-446655440000")
        True
        >>> is_valid_uuid("invalid")
        False
    """
    if not value or not isinstance(value, str):
        return False
    return bool(_UUID_PATTERN.match(value))