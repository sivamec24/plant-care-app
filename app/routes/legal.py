"""
Legal pages routes.

Handles Terms of Service and Privacy Policy pages.
"""

from __future__ import annotations
from flask import Blueprint, render_template


legal_bp = Blueprint("legal", __name__, url_prefix="/")


@legal_bp.route("/terms")
def terms():
    """
    Terms of Service page.

    Public page accessible to all users.
    """
    return render_template("legal/terms.html")


@legal_bp.route("/privacy")
def privacy():
    """
    Privacy Policy page.

    Public page accessible to all users.
    """
    return render_template("legal/privacy.html")
