"""
UI routes and request flow.

Serves the main page, handles submissions, validates input, runs moderation,
invokes the advice engine, pulls best-effort forecast/hourly data, and records
in-memory history. Keeps templates simple by passing everything they need.
"""

from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from datetime import datetime
from ..extensions import limiter
from ..services.ai import generate_advice, AI_LAST_ERROR
from ..services.moderation import run_moderation
from ..services import analytics
from ..utils.validation import validate_inputs, display_sanitize_short

# Optional forecast import (kept safe for environments/tests without it)

try:
    from ..services.weather import get_hourly_for_city
except Exception:  # pragma: no cover
    def get_hourly_for_city(city):
        return None
try:
    from ..services.weather import get_forecast_for_city
except Exception:  # pragma: no cover
    def get_forecast_for_city(city):
        return None

# --- Per-session history (client-side via Flask session) ---
MAX_HISTORY = 25

def _safe_trunc(s: str, limit: int = 600) -> str:
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    return (s[:limit] + "…") if len(s) > limit else s

def _get_history():
    """Return this user's history list from the session."""
    return session.get("history", [])

def _set_history(items):
    """Persist the history list back to the session, enforcing MAX_HISTORY."""
    session["history"] = list(items)[:MAX_HISTORY]
    session.modified = True  # ensure the cookie updates

def _push_history_item(item: dict):
    items = _get_history()
    # Light compaction to protect cookie size
    compact = {
        "ts": item.get("ts"),
        "plant": _safe_trunc(item.get("plant", ""), 120),
        "city": _safe_trunc(item.get("city", ""), 120),
        "care_context": _safe_trunc(item.get("care_context", ""), 80),
        "question": _safe_trunc(item.get("question", ""), 600),
        # Keep the whole answer if typically short; otherwise truncate
        "answer": _safe_trunc(item.get("answer", ""), 2000),
        "source": item.get("source"),
    }
    items.insert(0, compact)
    _set_history(items)

web_bp = Blueprint("web", __name__)

@limiter.exempt
@web_bp.route("/healthz")
def healthz():
    """Simple health endpoint to verify the server responds."""
    return "OK", 200


@web_bp.route("/debug")
def debug_info():
    """
    Lightweight status snapshot for troubleshooting.

    SECURITY:
    - Only available in DEBUG mode
    - Requires admin privileges (admin role)
    - Disabled by default (must enable DEBUG_ENDPOINTS_ENABLED in config)
    - Does not expose full API keys, only configuration status
    """
    # Check if debug endpoints are enabled (disabled by default for security)
    if not current_app.config.get("DEBUG_ENDPOINTS_ENABLED", False):
        return {"error": "Debug endpoints disabled"}, 404

    # Restrict to development environment only
    if not current_app.config.get("DEBUG", False):
        return {"error": "Not available in production"}, 404

    # Require admin privileges for access
    from app.utils.auth import get_current_user_id, is_admin
    user_id = get_current_user_id()
    if not user_id:
        return {"error": "Authentication required"}, 401

    if not is_admin(user_id):
        return {"error": "Admin privileges required"}, 403

    loaded_keys = [k for k in ("FLASK_SECRET_KEY", "OPENWEATHER_API_KEY", "OPENAI_API_KEY") if current_app.config.get(k)]

    # Only provide boolean configuration status - never expose key lengths or other details
    info = {
        "loaded_env_vars": loaded_keys,
        "flask_secret_key_set": bool(current_app.secret_key),
        "weather_api_configured": bool(current_app.config.get("OPENWEATHER_API_KEY")),
        "openai_configured": bool(current_app.config.get("OPENAI_API_KEY")),
        "gemini_configured": bool(current_app.config.get("GEMINI_API_KEY")),
        "history_len": len(_get_history()),
        # Sanitize error messages - only show generic info
        "ai_last_error": "Error occurred" if AI_LAST_ERROR else None,
    }
    return info


@web_bp.route("/history/clear", methods=["POST"])
@limiter.exempt  # optional: exempt from rate limit noise
def clear_history():
    session.pop("history", None)  # only this user's session history
    session.modified = True
    return redirect(url_for("web.assistant"))


@web_bp.route("/")
def index():
    """
    Homepage - renders based on authentication state:
    - Authenticated: redirect to Dashboard
    - Unauthenticated: render public landing page (SEO-indexable)
    """
    from ..utils.auth import get_current_user

    if get_current_user():
        return redirect(url_for("dashboard.index"))
    else:
        return render_template("home.html")


# Read rate string from config at request time (supports env/config changes)
def _ask_rate():
    return current_app.config.get("RATELIMIT_ASK", "8 per minute; 1 per 2 seconds; 200 per day")


# URL: /ask
# Endpoint: web.assistant
# Purpose: AI-powered plant care advice (GET: render form, POST: process question)
# UI Label: "Assistant" or "Care Assistant"
@web_bp.route("/ask", methods=["GET", "POST"])
@limiter.limit(_ask_rate, methods=["POST"])  # Only rate-limit POST requests
def assistant():
    """
    AI Plant Care Assistant page.

    GET: Render the assistant form with user's plants (if logged in)
    POST: Process AI question and return advice

    If user is authenticated, pre-fill city from their profile and show user plants.
    """
    from ..utils.auth import get_current_user_id
    from ..services.supabase_client import get_user_profile, get_user_plants

    # Get all user's plants for plant-aware AI
    user_plants = []
    user_id = get_current_user_id()
    default_city = None

    if user_id:
        # Get user profile to pre-fill city
        profile = get_user_profile(user_id)
        if profile:
            default_city = profile.get("city")
        # Get all user's plants (will display in horizontal scrollable carousel)
        # Only fetch minimal fields needed for carousel + location for AI context
        user_plants = get_user_plants(user_id, fields="id,name,nickname,photo_url,photo_url_thumb,location")

    # Handle GET request - render form
    if request.method == "GET":
        today_str = datetime.now().strftime("%Y-%m-%d")
        # Build form_values from query params and defaults
        form_values = {}
        selected_plant_id = None

        # Handle plant_id query param (from plant/reminder view links)
        if request.args.get("plant_id") and user_id:
            plant_id = request.args.get("plant_id")
            # Find the plant in user's plants list
            matching_plant = next((p for p in user_plants if p.get("id") == plant_id), None)
            if matching_plant:
                form_values["plant"] = matching_plant.get("name", "")
                form_values["care_context"] = matching_plant.get("location", "indoor_potted")
                selected_plant_id = plant_id
        elif request.args.get("plant"):
            form_values["plant"] = request.args.get("plant")

        if request.args.get("city") or default_city:
            form_values["city"] = request.args.get("city") or default_city

        # Handle question query param (from SEO landing pages)
        if request.args.get("question"):
            form_values["question"] = request.args.get("question")

        return render_template(
            "index.html",
            answer=None,
            weather=None,
            forecast=None,
            hourly=None,
            form_values=form_values if form_values else None,
            history=_get_history(),
            has_history=len(_get_history()) > 0,
            source=None,
            ai_error=None,
            today_str=today_str,
            user_plants=user_plants,
            selected_plant_id=selected_plant_id,
        )

    # Handle POST request - process form submission
    payload, err_msg = validate_inputs(request.form)

    if err_msg:
        today_str = datetime.now().strftime("%Y-%m-%d")
        return render_template(
            "index.html",
            answer=display_sanitize_short(err_msg),
            weather=None,
            forecast=None,
            hourly=None,
            form_values={
                "plant": request.form.get("plant", ""),
                "city": request.form.get("city", ""),
                "care_context": request.form.get("care_context", "indoor_potted"),
                "question": request.form.get("question", ""),
            },
            history=_get_history(),
            has_history=len(_get_history()) > 0,
            source="rule",
            ai_error=None,
            today_str=today_str,
            user_plants=user_plants,
        ), 400

    plant = payload["plant"]
    city = payload["city"]
    care_context = payload["care_context"]
    question = payload["question"]

    # Get selected plant ID for context (if user clicked a plant card)
    selected_plant_id = request.form.get("selected_plant_id")

    allowed, reason = run_moderation(question)
    if not allowed:
        today_str = datetime.now().strftime("%Y-%m-%d")
        return render_template(
            "index.html",
            answer=display_sanitize_short(f"Question blocked by content policy: {reason}"),
            weather=None,
            forecast=None,
            hourly=None,
            form_values=payload,
            history=_get_history(),
            has_history=len(_get_history()) > 0,
            source="rule",
            ai_error=None,
            today_str=today_str,
            user_plants=user_plants,
        ), 400

    # Advice engine returns (answer, weather, source)
    # Pass user_id and selected_plant_id for AI context integration
    answer, weather, source = generate_advice(
        question=question,
        plant=plant,
        city=city,
        care_context=care_context,
        user_id=user_id,  # NEW: Enable AI context
        selected_plant_id=selected_plant_id,  # NEW: Plant-specific context
    )

    # Hourly (best-effort): if the weather payload includes an 'hourly' list
    hourly = None
    if isinstance(weather, dict):
        raw = weather.get("hourly")
        if isinstance(raw, list) and raw:
            today_str = datetime.now().strftime("%Y-%m-%d")
            filtered = [h for h in raw if (
                (isinstance(h, dict) and (
                    h.get("date") == today_str or
                    h.get("day_iso") == today_str or
                    (isinstance(h.get("dt_iso"), str) and h["dt_iso"].startswith(today_str)) or
                    h.get("is_today") is True
                ))
            )]
            hourly = filtered if filtered else raw[:8]
    # Best-effort fetch if not present
    if (not hourly) and city:
        hourly = get_hourly_for_city(city)
    if isinstance(hourly, list) and not hourly:
        hourly = None

    # Forecast (best-effort): today's high/low merged into the Today card,
    # then up to 5 future days shown as separate cards
    forecast = get_forecast_for_city(city) if city else None
    if isinstance(forecast, list):
        forecast = forecast[:6]  # today + 5 future days
        # Blend current temp into today's high/low so the card reflects
        # the full day range, not just remaining future hours
        if forecast and forecast[0].get("is_today") and weather:
            cur_c = weather.get("temp_c")
            if isinstance(cur_c, (int, float)):
                cur_f = round((cur_c * 9 / 5) + 32, 1)
                today = forecast[0]
                if cur_c > today["temp_max_c"]:
                    today["temp_max_c"] = round(cur_c, 1)
                    today["temp_max_f"] = cur_f
                if cur_c < today["temp_min_c"]:
                    today["temp_min_c"] = round(cur_c, 1)
                    today["temp_min_f"] = cur_f

    # Record history
    _push_history_item({
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "plant": plant,
        "city": city,
        "care_context": care_context,
        "question": question,
        "answer": answer,
        "source": source,
    })

    # Track analytics event
    if user_id:
        analytics.track_event(
            user_id,
            analytics.EVENT_AI_QUESTION_ASKED,
            {
                "plant": plant,
                "care_context": care_context,
                "source": source
            }
        )

    today_str = datetime.now().strftime("%Y-%m-%d")
    return render_template(
        "index.html",
        answer=answer,
        weather=weather,
        forecast=forecast,
        hourly=hourly,
        form_values={"plant": plant, "city": city, "care_context": care_context, "question": question},
        history=_get_history(),
        has_history=len(_get_history()) > 0,
        source=source,
        ai_error=AI_LAST_ERROR,
        today_str=today_str,
        user_plants=user_plants,
    )