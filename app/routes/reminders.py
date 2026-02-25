"""
Reminder routes for plant care scheduling.

Handles displaying, creating, updating, and completing reminders.
"""

from __future__ import annotations
from datetime import date
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, jsonify
from app.utils.auth import require_auth, get_current_user_id
from app.utils.validation import is_valid_uuid, safe_referrer_or
from app.services import reminders as reminder_service
from app.services import analytics
from app.services.supabase_client import get_user_profile

reminders_bp = Blueprint("reminders", __name__, url_prefix="/reminders")


def _validate_custom_interval(frequency: str, custom_interval_days) -> tuple:
    """
    Validate and parse custom interval days for reminders.

    Args:
        frequency: The frequency type (e.g., "custom", "weekly")
        custom_interval_days: The raw custom interval value from form

    Returns:
        Tuple of (parsed_value, error_message).
        If frequency is not "custom", returns (None, None).
        If valid, returns (int_value, None).
        If invalid, returns (None, error_message).
    """
    if frequency != "custom":
        return None, None

    try:
        interval = int(custom_interval_days)
        if interval < 1 or interval > 365:
            return None, "Custom interval must be between 1 and 365 days."
        return interval, None
    except (ValueError, TypeError):
        return None, "Invalid custom interval days."


@reminders_bp.route("/")
@require_auth
def index():
    """Display all user's reminders (due, upcoming, and all)."""
    user_id = get_current_user_id()

    # Get reminders
    due_reminders = reminder_service.get_due_reminders(user_id)
    upcoming_reminders = reminder_service.get_upcoming_reminders(user_id, days=7)
    all_reminders = reminder_service.get_user_reminders(user_id, active_only=True)
    stats = reminder_service.get_reminder_stats(user_id)

    return render_template(
        "reminders/index.html",
        due_reminders=due_reminders,
        upcoming_reminders=upcoming_reminders,
        all_reminders=all_reminders,
        stats=stats,
    )


@reminders_bp.route("/history")
@require_auth
def history():
    """Display completed/inactive reminders history."""
    user_id = get_current_user_id()

    # Get inactive reminders
    inactive_reminders = reminder_service.get_user_reminders(user_id, active_only=False)

    # Filter to only inactive ones and sort by completion date (most recent first)
    inactive_reminders = [
        r for r in inactive_reminders if not r.get("is_active", True)
    ]
    # Sort by last_completed_at, falling back to updated_at, then empty string
    # Use 'or' instead of nested get() to handle None values properly
    inactive_reminders.sort(
        key=lambda r: r.get("last_completed_at") or r.get("updated_at") or "",
        reverse=True
    )

    return render_template(
        "reminders/history.html",
        inactive_reminders=inactive_reminders,
    )


@reminders_bp.route("/create", methods=["GET", "POST"])
@require_auth
def create():
    """Create a new reminder."""
    user_id = get_current_user_id()

    if request.method == "POST":
        # Get form data
        plant_id = request.form.get("plant_id", "").strip()
        reminder_type = request.form.get("reminder_type", "watering")
        title = request.form.get("title", "").strip()
        frequency = request.form.get("frequency", "weekly")
        custom_interval_days = request.form.get("custom_interval_days")
        notes = request.form.get("notes", "").strip()
        skip_weather = request.form.get("skip_weather_adjustment") == "on"

        # Validation
        if not plant_id:
            flash("Please select a plant.", "error")
            return redirect(url_for("reminders.create"))

        if not title:
            flash("Reminder title is required.", "error")
            return redirect(url_for("reminders.create"))

        # Validate custom interval
        custom_interval_days, interval_error = _validate_custom_interval(frequency, custom_interval_days)
        if interval_error:
            flash(interval_error, "error")
            return redirect(url_for("reminders.create"))

        # Create reminder
        reminder, error = reminder_service.create_reminder(
            user_id=user_id,
            plant_id=plant_id,
            reminder_type=reminder_type,
            title=title,
            frequency=frequency,
            custom_interval_days=custom_interval_days,
            notes=notes or None,
            skip_weather_adjustment=skip_weather,
        )

        if error:
            flash(f"Error creating reminder: {error}", "error")
            return redirect(url_for("reminders.create"))

        # Track analytics event
        analytics.track_event(
            user_id,
            analytics.EVENT_REMINDER_CREATED,
            {
                "reminder_id": reminder["id"],
                "reminder_type": reminder_type,
                "frequency": frequency
            }
        )

        flash(f"Reminder created: {title}", "success")
        return redirect(url_for("reminders.index"))

    # GET request - show form
    # Get user's plants for dropdown
    from app.services.supabase_client import get_user_plants
    plants = get_user_plants(user_id)

    if not plants:
        flash("Please add a plant before creating reminders.", "warning")
        return redirect(url_for("plants.add"))

    # Check for pre-selected plant from query param
    preselected_plant_id = request.args.get("plant_id")
    preselected_plant = None

    if preselected_plant_id:
        # Validate that the plant belongs to the user
        preselected_plant = next(
            (p for p in plants if p["id"] == preselected_plant_id),
            None
        )
        if not preselected_plant:
            preselected_plant_id = None  # Reset if invalid

    return render_template(
        "reminders/create.html",
        plants=plants,
        reminder_types=reminder_service.REMINDER_TYPE_NAMES,
        preselected_plant_id=preselected_plant_id,
        preselected_plant=preselected_plant,
    )


@reminders_bp.route("/<reminder_id>")
@require_auth
def view(reminder_id):
    """View a single reminder."""
    # Validate UUID format before database query
    if not is_valid_uuid(reminder_id):
        flash("Invalid reminder ID.", "error")
        return redirect(url_for("reminders.index"))

    user_id = get_current_user_id()

    reminder = reminder_service.get_reminder_by_id(reminder_id, user_id)

    if not reminder:
        flash("Reminder not found.", "error")
        return redirect(url_for("reminders.index"))

    return render_template("reminders/view.html", reminder=reminder)


@reminders_bp.route("/<reminder_id>/edit", methods=["GET", "POST"])
@require_auth
def edit(reminder_id):
    """Edit a reminder."""
    # Validate UUID format before database query
    if not is_valid_uuid(reminder_id):
        flash("Invalid reminder ID.", "error")
        return redirect(url_for("reminders.index"))

    user_id = get_current_user_id()

    reminder = reminder_service.get_reminder_by_id(reminder_id, user_id)

    if not reminder:
        flash("Reminder not found.", "error")
        return redirect(url_for("reminders.index"))

    if request.method == "POST":
        # Get form data
        title = request.form.get("title", "").strip()
        frequency = request.form.get("frequency", "weekly")
        custom_interval_days = request.form.get("custom_interval_days")
        notes = request.form.get("notes", "").strip()
        skip_weather = request.form.get("skip_weather_adjustment") == "on"
        next_due_str = request.form.get("next_due", "").strip()

        # Validation
        if not title:
            flash("Reminder title is required.", "error")
            return render_template("reminders/edit.html", reminder=reminder, today=date.today().isoformat())

        # Validate custom interval
        custom_interval_days, interval_error = _validate_custom_interval(frequency, custom_interval_days)
        if interval_error:
            flash(interval_error, "error")
            return render_template("reminders/edit.html", reminder=reminder, today=date.today().isoformat())

        # Build update data
        update_data = {
            "title": title,
            "frequency": frequency,
            "custom_interval_days": custom_interval_days,
            "notes": notes or None,
            "skip_weather_adjustment": skip_weather,
        }

        # Handle due date change
        if next_due_str:
            try:
                next_due_date = date.fromisoformat(next_due_str)
                if next_due_date < date.today():
                    flash("Due date cannot be in the past.", "error")
                    return render_template("reminders/edit.html", reminder=reminder, today=date.today().isoformat())
                update_data["next_due"] = next_due_str
                # Clear weather adjustment when user manually changes date
                update_data["weather_adjusted_due"] = None
                update_data["weather_adjustment_reason"] = None
            except ValueError:
                flash("Invalid date format.", "error")
                return render_template("reminders/edit.html", reminder=reminder, today=date.today().isoformat())

        # Update reminder
        updated, error = reminder_service.update_reminder(
            reminder_id=reminder_id,
            user_id=user_id,
            **update_data,
        )

        if error:
            flash(f"Error updating reminder: {error}", "error")
            return render_template("reminders/edit.html", reminder=reminder, today=date.today().isoformat())

        flash("Reminder updated successfully.", "success")
        return redirect(url_for("reminders.view", reminder_id=reminder_id))

    return render_template("reminders/edit.html", reminder=reminder, today=date.today().isoformat())


# SECURITY: All redirects below use safe_referrer_or() which validates the
# Referer header for same-origin, path-only, and allowed-prefix before use.
# See app/utils/validation.py:132. CodeQL py/url-redirection alerts on these
# lines are false positives — dismiss in GitHub Security tab.


@reminders_bp.route("/<reminder_id>/complete", methods=["POST"])
@require_auth
def complete(reminder_id):
    """Mark a reminder as complete."""
    # Validate UUID format before database query
    if not is_valid_uuid(reminder_id):
        flash("Invalid reminder ID.", "error")
        return redirect(url_for("reminders.index"))

    user_id = get_current_user_id()

    success, error = reminder_service.mark_reminder_complete(reminder_id, user_id)

    if not success:
        flash(f"Error completing reminder: {error}", "error")
        return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer

    # Track analytics event
    analytics.track_event(
        user_id,
        analytics.EVENT_REMINDER_COMPLETED,
        {"reminder_id": reminder_id}
    )

    flash("Reminder marked complete! Next reminder scheduled.", "success")
    return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer


@reminders_bp.route("/bulk-complete", methods=["POST"])
@require_auth
def bulk_complete():
    """Mark all due reminders as complete."""
    user_id = get_current_user_id()

    # Get all due reminders
    due_reminders = reminder_service.get_due_reminders(user_id)

    completed_count = 0
    errors = []

    for reminder in due_reminders:
        success, error = reminder_service.mark_reminder_complete(reminder["id"], user_id)
        if success:
            completed_count += 1
        else:
            errors.append(f"{reminder['title']}: {error}")

    if completed_count > 0:
        flash(f"✓ Marked {completed_count} reminder{'s' if completed_count != 1 else ''} complete!", "success")

    if errors:
        flash(f"Some reminders failed: {'; '.join(errors[:3])}", "error")

    return redirect(url_for("reminders.index"))


@reminders_bp.route("/<reminder_id>/snooze", methods=["POST"])
@require_auth
def snooze(reminder_id):
    """Snooze a reminder by N days."""
    # Validate UUID format before database query
    if not is_valid_uuid(reminder_id):
        flash("Invalid reminder ID.", "error")
        return redirect(url_for("reminders.index"))

    user_id = get_current_user_id()

    # Get snooze days from form (default 1)
    try:
        days = int(request.form.get("days", 1))
    except ValueError:
        days = 1

    success, error = reminder_service.snooze_reminder(reminder_id, user_id, days)

    if not success:
        flash(f"Error snoozing reminder: {error}", "error")
        return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer

    # Track analytics event
    analytics.track_event(
        user_id,
        analytics.EVENT_REMINDER_SNOOZED,
        {"reminder_id": reminder_id, "snooze_days": days}
    )

    flash(f"Reminder snoozed for {days} day(s).", "success")
    return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer


@reminders_bp.route("/<reminder_id>/delete", methods=["POST"])
@require_auth
def delete(reminder_id):
    """Delete (deactivate) a reminder."""
    # Validate UUID format before database query
    if not is_valid_uuid(reminder_id):
        flash("Invalid reminder ID.", "error")
        return redirect(url_for("reminders.index"))

    user_id = get_current_user_id()

    success, error = reminder_service.delete_reminder(reminder_id, user_id)

    if not success:
        flash(f"Error deleting reminder: {error}", "error")
        return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer

    flash("Reminder deleted successfully.", "success")
    return redirect(url_for("reminders.index"))


@reminders_bp.route("/<reminder_id>/toggle-status", methods=["POST"])
@require_auth
def toggle_status(reminder_id):
    """Toggle reminder's active status (activate/deactivate)."""
    # Validate UUID format before database query
    if not is_valid_uuid(reminder_id):
        flash("Invalid reminder ID.", "error")
        return redirect(url_for("reminders.index"))

    user_id = get_current_user_id()
    if not user_id:
        flash("Please log in to toggle reminder status.", "error")
        return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer

    success, error = reminder_service.toggle_reminder_status(reminder_id, user_id)

    if not success:
        flash(f"Error toggling reminder status: {error}", "error")
        return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer

    flash("Reminder status updated successfully.", "success")
    return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer


@reminders_bp.route("/<reminder_id>/adjust-weather", methods=["POST"])
@require_auth
def adjust_weather(reminder_id):
    """Manually trigger weather adjustment for a reminder."""
    # Validate UUID format before database query
    if not is_valid_uuid(reminder_id):
        flash("Invalid reminder ID.", "error")
        return redirect(url_for("reminders.index"))

    user_id = get_current_user_id()

    # Get city from form or user profile
    city = request.form.get("city")
    if not city:
        profile = get_user_profile(user_id)
        city = profile.get("city") if profile else None

    if not city:
        flash("City required for weather adjustment.", "error")
        return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer

    # Get reminder to find plant location
    reminder = reminder_service.get_reminder_by_id(reminder_id, user_id)
    if not reminder:
        flash("Reminder not found.", "error")
        return redirect(url_for("reminders.index"))

    plant = reminder.get("plants", {})
    plant_location = plant.get("location", "indoor_potted")

    success, message, weather = reminder_service.adjust_reminder_for_weather(
        reminder_id, user_id, city, plant_location
    )

    if success:
        flash(f"Weather adjustment applied: {message}", "success")
    else:
        flash(f"No adjustment made: {message}", "info")

    return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer


@reminders_bp.route("/<reminder_id>/clear-weather", methods=["POST"])
@require_auth
def clear_weather(reminder_id):
    """Clear weather adjustment and revert to original schedule."""
    user_id = get_current_user_id()

    success, error = reminder_service.clear_weather_adjustment(reminder_id, user_id)

    if not success:
        flash(f"Error clearing weather adjustment: {error}", "error")
        return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer

    flash("Weather adjustment cleared. Reverted to original schedule.", "success")
    return redirect(safe_referrer_or(url_for("reminders.index")))  # safe: validated referrer


# JSON API endpoints for AJAX calls


@reminders_bp.route("/api/due-today", methods=["GET"])
@require_auth
def api_due_today():
    """Get due reminders as JSON (for AJAX/widgets)."""
    user_id = get_current_user_id()

    due_reminders = reminder_service.get_due_reminders(user_id)

    return jsonify({
        "success": True,
        "count": len(due_reminders),
        "reminders": due_reminders,
    })


@reminders_bp.route("/api/upcoming", methods=["GET"])
@require_auth
def api_upcoming():
    """Get upcoming reminders as JSON (for calendar view)."""
    user_id = get_current_user_id()

    days = request.args.get("days", 7, type=int)
    upcoming = reminder_service.get_upcoming_reminders(user_id, days)

    return jsonify({
        "success": True,
        "count": len(upcoming),
        "reminders": upcoming,
    })


@reminders_bp.route("/api/stats", methods=["GET"])
@require_auth
def api_stats():
    """Get reminder statistics as JSON."""
    user_id = get_current_user_id()

    stats = reminder_service.get_reminder_stats(user_id)

    return jsonify({
        "success": True,
        "stats": stats,
    })


@reminders_bp.route("/api/<reminder_id>/complete", methods=["POST"])
@require_auth
def api_complete(reminder_id):
    """
    Mark reminder complete via JSON API.

    Security: CSRF token required via X-CSRFToken header
    (automatically validated by Flask-WTF CSRFProtect)
    """
    user_id = get_current_user_id()

    # Validate reminder_id format (UUID)
    if not is_valid_uuid(reminder_id):
        return jsonify({"success": False, "error": "Invalid reminder ID"}), 400

    success, error = reminder_service.mark_reminder_complete(reminder_id, user_id)

    if success:
        return jsonify({"success": True, "message": "Reminder completed"})
    else:
        if error:
            current_app.logger.error(f"Complete reminder failed: {error}")
        return jsonify({"success": False, "error": "Failed to complete reminder"}), 400


@reminders_bp.route("/api/<reminder_id>/adjust", methods=["POST"])
@require_auth
def api_adjust(reminder_id):
    """
    Adjust reminder due date by N days via JSON API (for weather suggestions).

    Accepts positive days (postpone) or negative days (advance).
    Used when users accept weather-based adjustment suggestions.

    Request body:
        {
            "days": 2,  // positive = postpone, negative = advance
            "reason": "Heavy rain expected (0.5\" in 24h)"  // optional
        }

    Security: CSRF token required via X-CSRFToken header
    (automatically validated by Flask-WTF CSRFProtect)
    """
    user_id = get_current_user_id()

    # Validate reminder_id format (UUID)
    if not is_valid_uuid(reminder_id):
        return jsonify({"success": False, "error": "Invalid reminder ID"}), 400

    # Get days and reason from request body
    try:
        data = request.get_json()
        if not data or "days" not in data:
            return jsonify({"success": False, "error": "Missing 'days' parameter"}), 400

        days = int(data["days"])
        reason = data.get("reason")  # Optional parameter
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid 'days' value - must be an integer"}), 400

    # Validate days range
    if days < -7 or days > 30:
        return jsonify({"success": False, "error": "Days must be between -7 and +30"}), 400

    if days == 0:
        return jsonify({"success": False, "error": "Cannot adjust by 0 days"}), 400

    # Adjust reminder with optional reason
    success, error = reminder_service.adjust_reminder_by_days(reminder_id, user_id, days, reason)

    if success:
        # Track analytics event
        analytics.track_event(
            user_id,
            analytics.EVENT_REMINDER_SNOOZED,  # Reuse snooze event for weather adjustments
            {"reminder_id": reminder_id, "adjustment_days": days, "source": "weather_suggestion"}
        )

        action = "postponed" if days > 0 else "advanced"
        return jsonify({
            "success": True,
            "message": f"Reminder {action} by {abs(days)} day(s)"
        })
    else:
        if error:
            current_app.logger.error(f"Adjust reminder failed: {error}")
        return jsonify({"success": False, "error": "Failed to adjust reminder"}), 400


@reminders_bp.route("/<reminder_id>/toggle-weather", methods=["POST"])
@require_auth
def toggle_weather_adjustment(reminder_id):
    """
    Toggle weather adjustment opt-out for a specific reminder.

    Allows users to enable/disable automatic weather-based adjustments
    for individual reminders.

    Security: CSRF token required (Flask-WTF CSRFProtect)
    """
    user_id = get_current_user_id()

    # Get reminder to check current state
    reminder = reminder_service.get_reminder_by_id(reminder_id, user_id)
    if not reminder:
        flash("Reminder not found", "error")
        return redirect(url_for("reminders.index"))

    # Toggle skip_weather_adjustment flag
    current_value = reminder.get("skip_weather_adjustment", False)
    new_value = not current_value

    # Update reminder with new value
    success, error = reminder_service.update_reminder(
        reminder_id,
        user_id,
        skip_weather_adjustment=new_value
    )

    if success:
        if new_value:
            flash("Weather adjustments disabled for this reminder", "info")
        else:
            flash("Weather adjustments enabled for this reminder", "success")
    else:
        flash(f"Failed to update: {error}", "error")

    # Redirect back to referrer or reminder detail page
    return redirect(safe_referrer_or(url_for("reminders.view", reminder_id=reminder_id)))  # safe: validated referrer


@reminders_bp.route("/calendar")
@reminders_bp.route("/calendar/<int:year>/<int:month>")
@require_auth
def calendar(year=None, month=None):
    """
    Display care calendar view showing all reminders for a month.

    Args:
        year: Year to display (defaults to current year)
        month: Month to display (defaults to current month)
    """
    from datetime import datetime
    from calendar import monthcalendar, month_name, setfirstweekday, SUNDAY

    user_id = get_current_user_id()

    # Default to current month if not specified
    today = datetime.now()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    # Validate month range
    if not (1 <= month <= 12):
        flash("Invalid month specified.", "error")
        return redirect(url_for("reminders.calendar"))

    # Get reminders for this month
    reminders = reminder_service.get_reminders_for_month(user_id, year, month)

    # Group reminders by date
    from collections import defaultdict
    reminders_by_date = defaultdict(list)
    for reminder in reminders:
        if reminder.get("next_due"):
            # Extract date from next_due (format: YYYY-MM-DD)
            due_date = reminder["next_due"]
            reminders_by_date[due_date].append(reminder)

    # Set Sunday as first day of week (US convention)
    setfirstweekday(SUNDAY)

    # Get calendar grid (list of weeks, each week is a list of days)
    calendar_grid = monthcalendar(year, month)

    # Calculate previous and next month
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    return render_template(
        "reminders/calendar.html",
        year=year,
        month=month,
        month_name=month_name[month],
        calendar_grid=calendar_grid,
        reminders_by_date=dict(reminders_by_date),
        today=today.date(),
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
    )
