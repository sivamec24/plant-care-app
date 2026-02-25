"""
Defines JSON endpoints used by the front end.

Endpoints:
- /presets: Regional plant presets using geolocation or city
- /user/theme: Update user theme preferences
- /user/context: Get user context for AI (plants, reminders, activities)
- /user/plant/<id>/context: Get detailed context for specific plant
- /acknowledge-legal: Record user acknowledgment of legal updates
- /feedback/answer: Submit feedback on AI answers
"""

import uuid
from flask import Blueprint, request, jsonify, make_response, current_app, session
from ..utils.presets import infer_region_from_latlon, infer_region_from_city, region_presets
from ..utils.auth import require_auth, get_current_user_id
from ..utils.errors import sanitize_error, GENERIC_MESSAGES
from ..services import supabase_client, user_context
from ..extensions import limiter


api_bp = Blueprint("api", __name__)


@api_bp.before_request
def _enforce_ajax_for_mutations():
    """Enforce X-Requested-With header on all state-changing API requests.

    Provides CSRF protection for the entire API blueprint because:
    1. Custom headers cannot be set by cross-origin requests without CORS
    2. HTML forms cannot set custom headers
    3. Only JavaScript (same-origin) can set this header

    This replaces the per-endpoint @require_ajax() decorator pattern so
    new POST/PUT/DELETE endpoints are automatically protected.
    """
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return jsonify({
                "success": False,
                "error": "Invalid request. Please refresh the page and try again."
            }), 403


@api_bp.route("/presets")
def presets_api():
    """
    Decide region via:
      - ?lat=..&lon=.. (preferred)
      - else ?city=..
      - else default 'temperate'
    Returns a stable JSON payload for the client UI.
    """
    try:
        lat = request.args.get("lat", type=float)
        lon = request.args.get("lon", type=float)
        city = request.args.get("city", type=str)

        if lat is not None and lon is not None:
            region = infer_region_from_latlon(lat, lon)
        elif city:
            region = infer_region_from_city(city)
        else:
            region = "temperate"

        return jsonify({"region": region, "items": region_presets(region)})
    except Exception:
        # Never surface internal errors; return a safe fallback.
        return jsonify({"region": "temperate", "items": region_presets("temperate")})


@api_bp.route("/user/theme", methods=["POST"])
@require_auth
def update_theme():
    """
    Updates user's theme preference (light, dark, or auto).

    Security:
    - Requires authentication
    - Input validation (only allows 'light', 'dark', 'auto')
    - User can only update their own preference

    Request body (JSON):
        {
            "theme": "light" | "dark" | "auto"
        }

    Returns:
        {
            "success": true/false,
            "error": "error message" (if applicable)
        }
    """
    try:
        # Get user ID from session
        user_id = get_current_user_id()

        # Parse JSON body
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Invalid request body"}), 400

        theme = data.get("theme", "").strip().lower()

        # Validate theme value
        if theme not in ["light", "dark", "auto"]:
            return jsonify({
                "success": False,
                "error": "Invalid theme. Must be 'light', 'dark', or 'auto'"
            }), 400

        # Update theme in database
        success, error = supabase_client.update_user_theme(user_id, theme)

        if success:
            return jsonify({"success": True}), 200
        else:
            # Sanitize service layer error
            sanitized_msg = GENERIC_MESSAGES["database"]
            return jsonify({"success": False, "error": sanitized_msg}), 500

    except Exception as e:
        # Log the actual error for debugging, return sanitized message
        sanitized_msg = sanitize_error(e, "database", "Theme update failed")
        return jsonify({"success": False, "error": sanitized_msg}), 500


@api_bp.route("/user/context", methods=["GET"])
@require_auth
@limiter.limit("10 per minute")
def get_user_context():
    """
    Get consolidated user context for AI.

    Returns comprehensive context including:
    - User's plants (name, location, light)
    - Reminders (overdue, due today, upcoming week)
    - Recent care activities (last 7 days)
    - Summary statistics

    **Authentication required**

    Rate limit: 10 requests per minute

    Returns:
        200: JSON with user context
        401: Not authenticated
        429: Rate limit exceeded

    Example response:
        {
            "success": true,
            "context": {
                "plants": [...],
                "reminders": {...},
                "recent_activities": [...],
                "stats": {...}
            }
        }
    """
    user_id = get_current_user_id()

    try:
        context = user_context.get_user_context(user_id)
        return jsonify({
            "success": True,
            "context": context
        }), 200
    except Exception as e:
        sanitized_msg = sanitize_error(e, "database", "Failed to get user context")
        return jsonify({
            "success": False,
            "error": sanitized_msg
        }), 500


@api_bp.route("/user/plant/<plant_id>/context", methods=["GET"])
@require_auth
@limiter.limit("10 per minute")
def get_plant_context(plant_id: str):
    """
    Get detailed context for specific plant.

    Returns plant-specific context including:
    - Full plant details
    - Last 14 days of care activities
    - All active reminders for this plant
    - Plant-specific statistics

    **Authentication required**

    Rate limit: 10 requests per minute

    Args:
        plant_id: UUID of the plant

    Returns:
        200: JSON with plant context
        401: Not authenticated
        403: Access denied (not user's plant)
        404: Plant not found
        429: Rate limit exceeded

    Example response:
        {
            "success": true,
            "context": {
                "plant": {...},
                "activities": [...],
                "reminders": [...],
                "stats": {...}
            }
        }
    """
    user_id = get_current_user_id()

    try:
        context = user_context.get_plant_context(user_id, plant_id)

        # Check if plant was found
        if context.get("error"):
            return jsonify({
                "success": False,
                "error": context["error"]
            }), 404 if "not found" in context["error"].lower() else 403

        return jsonify({
            "success": True,
            "context": context
        }), 200
    except Exception as e:
        sanitized_msg = sanitize_error(e, "database", "Failed to get plant context")
        return jsonify({
            "success": False,
            "error": sanitized_msg
        }), 500


@api_bp.route("/acknowledge-legal", methods=["POST"])
@require_auth
@limiter.limit("10 per minute")
def acknowledge_legal():
    """Record that the user has acknowledged the latest legal updates."""
    try:
        user_id = get_current_user_id()
        success, error = supabase_client.update_legal_acknowledgment(user_id)
        if success:
            session["legal_acknowledged"] = True
            return jsonify({"success": True})
        return jsonify({"success": False, "error": GENERIC_MESSAGES["database"]}), 500
    except Exception as e:
        sanitized_msg = sanitize_error(e, "database", "Legal acknowledgment failed")
        return jsonify({"success": False, "error": sanitized_msg}), 500


@api_bp.route("/feedback/answer", methods=["POST"])
@limiter.limit("10 per minute")
def submit_answer_feedback():
    """
    Submit feedback for an AI answer.

    Available to both authenticated and unauthenticated users.
    Uses session cookie for anonymous tracking.

    Rate limit: 10 requests per minute

    Request body (JSON):
        {
            "rating": "yes" | "somewhat" | "no",
            "question": "...",
            "plant": "...",
            "city": "...",
            "care_context": "...",
            "ai_source": "openai" | "gemini" | "rule"
        }

    Returns:
        200: {"success": true}
        400: {"success": false, "error": "..."}
        500: {"success": false, "error": "..."}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Invalid request"}), 400

        # Validate rating
        rating = data.get("rating", "").strip().lower()
        if rating not in ["yes", "somewhat", "no"]:
            return jsonify({"success": False, "error": "Invalid rating"}), 400

        # Validate question exists
        question = data.get("question", "").strip()
        if not question:
            return jsonify({"success": False, "error": "Question is required"}), 400

        # Get user ID if authenticated (optional)
        user_id = None
        try:
            user_id = get_current_user_id()
        except Exception:
            pass

        # Get or generate session ID for anonymous users
        session_id = request.cookies.get("pcai_session_id")
        if not session_id and not user_id:
            session_id = str(uuid.uuid4())

        # Build feedback record
        feedback_data = {
            "user_id": user_id,
            "session_id": session_id if not user_id else None,
            "question": question[:600],  # Truncate for safety
            "plant": (data.get("plant") or "")[:120],
            "city": (data.get("city") or "")[:120],
            "care_context": (data.get("care_context") or "")[:80],
            "ai_source": data.get("ai_source") or None,
            "rating": rating,
            "page_url": (request.referrer or request.url or "")[:500],
            "user_agent": request.headers.get("User-Agent", "")[:255],
        }

        # Insert into database
        admin_client = supabase_client.get_admin_client()
        if not admin_client:
            return jsonify({"success": False, "error": "Service unavailable"}), 503

        result = admin_client.table("answer_feedback").insert(feedback_data).execute()

        if result.data:
            response = make_response(jsonify({"success": True}), 200)
            # Set session cookie for anonymous tracking if not already set
            if session_id and not request.cookies.get("pcai_session_id"):
                response.set_cookie(
                    "pcai_session_id",
                    session_id,
                    max_age=60 * 60 * 24 * 30,  # 30 days
                    httponly=True,
                    samesite="Lax",
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", True),
                )
            return response
        else:
            return jsonify({"success": False, "error": "Failed to save feedback"}), 500

    except Exception as e:
        sanitized_msg = sanitize_error(e, "database", "Feedback submission failed")
        return jsonify({"success": False, "error": sanitized_msg}), 500