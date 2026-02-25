"""
Data sanitization helpers for privacy-safe logging.

Functions here strip or mask PII so it can be safely written to logs
without exposing sensitive user data.
"""

from __future__ import annotations


def mask_email(email: str) -> str:
    """Mask email for safe logging (e.g., 'j***@example.com').

    Preserves only the first character of the local part and the full domain
    so operators can correlate log entries without exposing the full address.
    """
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    return f"{local[0]}***@{domain}" if local else f"***@{domain}"
