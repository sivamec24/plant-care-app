"""
Plant Care Guides for SEO.

Static guides for popular houseplants targeting long-tail keywords like
"monstera care guide", "how to water pothos", etc.

Each guide links to /ask for personalized AI advice.
"""

from __future__ import annotations
import json
import os
from flask import Blueprint, render_template, abort, current_app
from typing import Optional


guides_bp = Blueprint("guides", __name__, url_prefix="/plant-care-guides")

# Cache for guides data
_guides_cache: Optional[list] = None


def _load_guides() -> list:
    """Load guides data from JSON file, with caching."""
    global _guides_cache
    if _guides_cache is not None:
        return _guides_cache

    guides_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "guides.json"
    )

    try:
        with open(guides_path, "r", encoding="utf-8") as f:
            _guides_cache = json.load(f)
    except FileNotFoundError:
        current_app.logger.warning(f"Guides file not found: {guides_path}")
        _guides_cache = []

    return _guides_cache


def _get_guide_by_slug(slug: str) -> Optional[dict]:
    """Get a single guide by its URL slug."""
    guides = _load_guides()
    for guide in guides:
        if guide.get("slug") == slug:
            return guide
    return None


@guides_bp.route("/")
def index():
    """
    Plant care guides index page.

    Lists all available guides organized by category.
    """
    guides = _load_guides()
    return render_template("guides/index.html", guides=guides)


@guides_bp.route("/<slug>")
def view(slug: str):
    """
    Individual plant care guide.

    Displays detailed care information for a specific plant.
    """
    guide = _get_guide_by_slug(slug)
    if not guide:
        abort(404)

    return render_template("guides/guide.html", guide=guide)
