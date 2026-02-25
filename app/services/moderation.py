"""
Lightweight text moderation.

Checks user input and returns (allowed, reason). If blocked, 'reason' is a
short message suitable for UI display. Replace with a stronger policy or a
vendor API if you need more coverage.
"""

from __future__ import annotations
import re
from typing import Tuple

# Very light heuristic example; extend as needed.
# Uses word boundaries (\b) to avoid false positives on plant terms like
# "shoot" (plant growth), "killer bee", etc.

_BLOCKLIST = [
    "hate", "suicide", "bomb", "kill", "murder", "shoot", "terror", "nsfw",
]

_BLOCKLIST_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in _BLOCKLIST) + r")\b",
    re.IGNORECASE,
)


def run_moderation(text: str) -> Tuple[bool, str | None]:
    """
    Returns (allowed, reason). Word-boundary match against a tiny blocklist.
    This is intentionally minimal to avoid false positives.
    """
    t = text or ""
    match = _BLOCKLIST_PATTERN.search(t)
    if match:
        return False, f"contains disallowed content: \u201c{match.group()}\u201d"
    return True, None