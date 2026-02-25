"""
Dashboard routes for authenticated users.

Shows:
- Plant collection
- Reminders due today
- Trial status
- Quick stats
"""

from __future__ import annotations
import hashlib
from datetime import date
import json
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, Response
from app.utils.auth import require_auth, get_current_user_id
from app.extensions import limiter
from app.services import supabase_client
from app.services.supabase_client import TIMEZONE_GROUPS
from app.services import reminders as reminder_service
from app.services.weather import (
    get_weather_for_city,
    get_precipitation_forecast_24h,
    get_temperature_extremes_forecast
)


dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/")
@require_auth
def index():
    """
    Main dashboard view.

    Shows:
    - Greeting
    - Trial status banner (if applicable)
    - Plant count
    - Reminders due today (placeholder for now)
    - Quick actions
    """
    user_id = get_current_user_id()

    # Get user profile and stats
    profile = supabase_client.get_user_profile(user_id)
    plant_count = supabase_client.get_plant_count(user_id)
    is_premium = supabase_client.is_premium(user_id)
    is_in_trial = supabase_client.is_in_trial(user_id)
    trial_days = supabase_client.trial_days_remaining(user_id)
    has_premium_access = supabase_client.has_premium_access(user_id)

    # Get user's plants for carousel (limit 20 for performance)
    latest_plants = supabase_client.get_user_plants(user_id, 20, 0)

    # Get reminder stats and due reminders with weather adjustments
    reminder_stats = reminder_service.get_reminder_stats(user_id)
    due_reminders, weather_suggestions = reminder_service.get_due_reminders_with_adjustments(user_id)

    # Fetch weather context for dashboard alerts (Phase 2C)
    weather_context = None
    city = profile.get("city") if profile else None
    if city:
        current_weather = get_weather_for_city(city)
        forecast_precip = get_precipitation_forecast_24h(city)
        forecast_temps = get_temperature_extremes_forecast(city, hours=48)

        # Build weather alerts based on thresholds
        weather_alerts = []

        if forecast_precip is not None and forecast_precip >= 0.5:
            weather_alerts.append({
                "type": "rain",
                "icon": "🌧️",
                "message": f"Heavy rain expected ({forecast_precip:.1f}\" in 24h). Outdoor watering postponed."
            })
        elif forecast_precip is not None and forecast_precip >= 0.25:
            weather_alerts.append({
                "type": "rain",
                "icon": "🌦️",
                "message": f"Rain expected ({forecast_precip:.1f}\" in 24h). Consider postponing outdoor watering."
            })

        if forecast_temps and forecast_temps.get("freeze_risk"):
            min_f = forecast_temps.get("temp_min_f", 32)
            weather_alerts.append({
                "type": "freeze",
                "icon": "❄️",
                "message": f"Freeze warning ({min_f}°F). Protect outdoor plants."
            })

        if forecast_temps and forecast_temps.get("temp_max_f", 0) >= 95:
            max_f = forecast_temps["temp_max_f"]
            weather_alerts.append({
                "type": "heat",
                "icon": "🔥",
                "message": f"Extreme heat ({max_f}°F). Water early morning or evening."
            })

        weather_context = {
            "current": current_weather,
            "alerts": weather_alerts
        }

    # Build reassurance context for "all clear" state
    reassurance_parts = []
    if weather_context and weather_context.get("current"):
        w_city = weather_context["current"].get("city", "")
        if w_city and not weather_context.get("alerts"):
            reassurance_parts.append(f"Conditions look good in {w_city}")
    upcoming = reminder_stats.get("upcoming_7_days", 0) if reminder_stats else 0
    if upcoming > 0:
        reassurance_parts.append(
            f"{upcoming} task{'s' if upcoming != 1 else ''} coming up this week"
        )
    else:
        reassurance_parts.append("No upcoming tasks this week")
    reassurance_message = " \u00b7 ".join(reassurance_parts) if reassurance_parts else "Your plants are on track."

    # Rotating daily care tip for "all clear" state
    care_tips = [
        "Overwatering is more common than underwatering. When in doubt, wait a day.",
        "Most houseplants prefer to dry out slightly between waterings.",
        "Yellow leaves? Check drainage before adding more water.",
        "Morning light is gentler than afternoon sun for most indoor plants.",
        "Dust on leaves blocks light. A quick wipe goes a long way.",
        "Grouping plants together raises humidity naturally.",
        "Room temperature water is easier on roots than cold water.",
    ]
    day_index = int(hashlib.md5(str(date.today()).encode(), usedforsecurity=False).hexdigest(), 16) % len(care_tips)
    daily_tip = care_tips[day_index]

    return render_template(
        "dashboard/index.html",
        profile=profile,
        plant_count=plant_count,
        is_premium=is_premium,
        is_in_trial=is_in_trial,
        trial_days=trial_days,
        has_premium_access=has_premium_access,
        latest_plants=latest_plants,
        reminder_stats=reminder_stats,
        due_reminders=due_reminders,
        weather_suggestions=weather_suggestions,
        weather_context=weather_context,
        reassurance_message=reassurance_message,
        daily_tip=daily_tip,
    )


@dashboard_bp.route("/account", methods=["GET", "POST"])
@require_auth
def account():
    """
    Account settings page.

    GET: Shows account settings form
    POST: Updates user preferences (city)

    Shows:
    - Email
    - Plan type
    - Subscription management
    - Location preferences
    """
    user_id = get_current_user_id()
    profile = supabase_client.get_user_profile(user_id)

    if request.method == "POST":
        # Track if any updates were made
        updates_made = []

        # Handle timezone update FIRST (manual override) - before city update
        # Only update if user explicitly selected a timezone (not the default empty option)
        timezone_from_form = request.form.get("timezone", "").strip()
        timezone_explicitly_set = False
        if timezone_from_form:
            # User selected a specific timezone - this is a manual override
            success, error = supabase_client.update_user_timezone(user_id, timezone_from_form)
            if success:
                updates_made.append("timezone")
                timezone_explicitly_set = True
                session.pop("user_timezone", None)  # clear cache
            else:
                flash(f"Failed to update timezone: {error}", "error")

        # Handle city update
        city = request.form.get("city", "").strip()
        if "city" in request.form:  # Only update if field is present
            success, error = supabase_client.update_user_city(user_id, city)
            if success:
                if city:
                    updates_made.append("location")
                    # If timezone wasn't explicitly set, note that it was auto-derived
                    if not timezone_explicitly_set:
                        # Refresh profile to get the auto-derived timezone
                        updated_profile = supabase_client.get_user_profile(user_id)
                        if updated_profile and updated_profile.get("timezone"):
                            updates_made.append(f"timezone auto-detected")
                            session.pop("user_timezone", None)  # clear cache
                else:
                    updates_made.append("location (cleared)")
            else:
                flash(f"Failed to update location: {error}", "error")

        # Handle theme update
        theme = request.form.get("theme", "").strip().lower()
        if theme and theme in ["light", "dark", "auto"]:
            success, error = supabase_client.update_user_theme(user_id, theme)
            if success:
                updates_made.append("theme")
            else:
                flash(f"Failed to update theme: {error}", "error")

        # Handle marketing email preference update
        current_marketing_opt_in = profile.get("marketing_opt_in", False) if profile else False
        new_marketing_opt_in = request.form.get("marketing_opt_in") == "on"

        if new_marketing_opt_in != current_marketing_opt_in:
            success, error = supabase_client.update_marketing_preference(
                user_id, marketing_opt_in=new_marketing_opt_in
            )
            if success:
                # Sync with Resend Audience
                from app.services.marketing_emails import sync_to_resend_audience

                email = profile.get("email") if profile else None
                if email:
                    sync_to_resend_audience(email, subscribed=new_marketing_opt_in)

                if new_marketing_opt_in:
                    updates_made.append("email preferences (subscribed)")
                else:
                    updates_made.append("email preferences (unsubscribed)")
            else:
                flash(f"Failed to update email preferences: {error}", "error")

        # Handle plant care preferences update (AI personalization)
        experience_level = request.form.get("experience_level", "").strip()
        primary_goal = request.form.get("primary_goal", "").strip()
        time_commitment = request.form.get("time_commitment", "").strip()
        environment_preference = request.form.get("environment_preference", "").strip()

        # Check if any preference was provided
        if experience_level or primary_goal or time_commitment or environment_preference:
            success, error = supabase_client.update_user_preferences(
                user_id,
                experience_level=experience_level,
                primary_goal=primary_goal,
                time_commitment=time_commitment,
                environment_preference=environment_preference
            )
            if success:
                updates_made.append("plant care preferences")
            else:
                flash(f"Failed to update plant care preferences: {error}", "error")

        # Handle hemisphere preference update
        hemisphere = request.form.get("hemisphere", "").strip()
        # Only update if the field was present in the form
        if "hemisphere" in request.form:
            # Empty string means auto-detect
            success, error = supabase_client.update_hemisphere_preference(
                user_id, hemisphere if hemisphere else None
            )
            if success:
                if hemisphere:
                    updates_made.append(f"hemisphere ({hemisphere})")
                else:
                    updates_made.append("hemisphere (auto-detect)")
            else:
                flash(f"Failed to update hemisphere: {error}", "error")

        # Show success message if any updates were made
        if updates_made:
            flash(f"Preferences updated: {', '.join(updates_made)}", "success")
            # Refresh profile to show updated data
            profile = supabase_client.get_user_profile(user_id)

    # Compute auto-detected hemisphere from city latitude (similar to timezone)
    detected_hemisphere = None
    if profile and profile.get("city") and not profile.get("hemisphere"):
        from app.services.weather import get_city_latitude
        lat = get_city_latitude(profile.get("city"))
        if lat is not None:
            detected_hemisphere = "Southern" if lat < 0 else "Northern"

    return render_template(
        "dashboard/account.html",
        profile=profile,
        timezone_groups=TIMEZONE_GROUPS,
        detected_hemisphere=detected_hemisphere,
    )


@dashboard_bp.route("/export", methods=["POST"])
@require_auth
@limiter.limit("3 per hour")
def export_data():
    """Export all user data as a JSON download (GDPR Article 20)."""
    user_id = get_current_user_id()
    data = supabase_client.export_user_data(user_id)

    if "error" in data:
        flash("Unable to export data. Please try again later.", "error")
        return redirect(url_for("dashboard.account"))

    response = Response(
        json.dumps(data, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=plantcareai-data-export.json"}
    )
    return response


@dashboard_bp.route("/delete-account", methods=["POST"])
@require_auth
@limiter.limit("3 per hour")
def delete_account():
    """Permanently delete user account and all data (GDPR Article 17)."""
    user_id = get_current_user_id()

    # Require explicit confirmation
    if request.form.get("confirm_delete") != "DELETE":
        flash("Please type DELETE to confirm account deletion.", "error")
        return redirect(url_for("dashboard.account"))

    success, message = supabase_client.delete_user_account(user_id)

    if not success:
        flash(message, "error")
        return redirect(url_for("dashboard.account"))

    # Clear session and redirect to home
    session.clear()
    flash("Your account and all data have been permanently deleted.", "info")
    return redirect(url_for("web.index"))
