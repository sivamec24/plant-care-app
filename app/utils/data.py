"""
Shared utilities for loading JSON data files from app/data/.
"""

from __future__ import annotations
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def load_data_file(filename: str) -> list:
    """Load a JSON data file from app/data/.

    Returns an empty list if the file is not found.
    """
    filepath = os.path.join(_DATA_DIR, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
