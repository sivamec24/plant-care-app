"""
Features page routes.

Shows available features and plans:
- Free tier (no cost, up to 20 plants)
- Premium tier (coming soon)
- FAQ section
"""

from __future__ import annotations
from flask import Blueprint, render_template
from app.utils.auth import optional_auth


pricing_bp = Blueprint("pricing", __name__, url_prefix="/features")


@pricing_bp.route("/")
@optional_auth
def index():
    """
    Public pricing page showing all tiers.

    Accessible to both guests and logged-in users.
    """
    return render_template("pricing/index.html")
