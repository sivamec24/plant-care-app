"""
Jinja2 template filters.

Keeps filter logic out of the app factory so it can be unit-tested easily.
"""

from __future__ import annotations
from datetime import date, datetime


def relative_date(value):
    """Convert a date/datetime to relative format like 'today', 'yesterday', '3 days ago'."""
    if not value:
        return "Unknown"

    # Parse string to date if needed
    if isinstance(value, str):
        try:
            # Handle ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            value = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            return value[:10] if len(value) >= 10 else value
    elif isinstance(value, datetime):
        value = value.date()

    today = date.today()
    delta = (today - value).days

    if delta == 0:
        return "Today"
    elif delta == 1:
        return "Yesterday"
    elif delta < 7:
        return f"{delta} days ago"
    elif delta < 14:
        return "1 week ago"
    elif delta < 30:
        weeks = delta // 7
        return f"{weeks} weeks ago"
    elif delta < 60:
        return "1 month ago"
    else:
        # Fall back to formatted date for older entries
        return value.strftime("%b %d, %Y")