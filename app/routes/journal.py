"""
Journal/Activity routes for plant care tracking.

Handles creating, viewing, and managing plant care activities.
"""

from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from app.utils.auth import require_auth, get_current_user_id
from app.utils.photo_handler import handle_photo_upload, delete_all_photo_versions
from app.utils.errors import sanitize_error, log_info
from app.utils.validation import is_valid_uuid
from app.services import journal as journal_service
from app.services import analytics
from app.services.supabase_client import get_plant_by_id, upload_plant_photo_versions, delete_plant_photo
from app.extensions import limiter
from werkzeug.utils import secure_filename

journal_bp = Blueprint("journal", __name__, url_prefix="/journal")


@journal_bp.route("/plant/<plant_id>")
@require_auth
def view_plant_journal(plant_id):
    """View all journal entries for a specific plant."""
    # Validate UUID format before database query
    if not is_valid_uuid(plant_id):
        flash("Invalid plant ID.", "error")
        return redirect(url_for("plants.index"))

    user_id = get_current_user_id()

    # Get plant details
    plant = get_plant_by_id(plant_id, user_id)
    if not plant:
        flash("Plant not found.", "error")
        return redirect(url_for("plants.index"))

    # Get journal entries
    actions = journal_service.get_plant_actions(plant_id, user_id)
    stats = journal_service.get_action_stats(plant_id, user_id)

    return render_template(
        "journal/plant_journal.html",
        plant=plant,
        actions=actions,
        stats=stats,
        action_type_names=journal_service.ACTION_TYPE_NAMES,
        action_type_emojis=journal_service.ACTION_TYPE_EMOJIS,
    )


@journal_bp.route("/plant/<plant_id>/add", methods=["GET", "POST"])
@require_auth
@limiter.limit(lambda: current_app.config['UPLOAD_RATE_LIMIT'])
def add_entry(plant_id):
    """Add a new journal entry for a plant."""
    # Validate UUID format before database query
    if not is_valid_uuid(plant_id):
        flash("Invalid plant ID.", "error")
        return redirect(url_for("plants.index"))

    user_id = get_current_user_id()

    # Get plant details
    plant = get_plant_by_id(plant_id, user_id)
    if not plant:
        flash("Plant not found.", "error")
        return redirect(url_for("plants.index"))

    if request.method == "POST":
        # Get form data
        action_type = request.form.get("action_type", "note")
        notes = request.form.get("notes", "").strip()
        amount_ml = request.form.get("amount_ml")

        # Validation
        if action_type not in journal_service.ACTION_TYPE_NAMES:
            flash("Invalid action type.", "error")
            return render_template(
                "journal/add_entry.html",
                plant=plant,
                action_types=journal_service.ACTION_TYPE_NAMES,
            )

        # Convert amount_ml to int if provided
        if amount_ml:
            try:
                amount_ml = int(amount_ml)
                if amount_ml <= 0:
                    flash("Amount must be greater than 0.", "error")
                    return render_template(
                        "journal/add_entry.html",
                        plant=plant,
                        action_types=journal_service.ACTION_TYPE_NAMES,
                    )
            except ValueError:
                flash("Invalid amount value.", "error")
                return render_template(
                    "journal/add_entry.html",
                    plant=plant,
                    action_types=journal_service.ACTION_TYPE_NAMES,
                )
        else:
            amount_ml = None

        # Handle photo upload (consolidated helper)
        file = request.files.get("photo")
        photo_url, photo_url_thumb = handle_photo_upload(file, user_id)

        # If upload failed with error, return early
        if file and file.filename and not photo_url:
            return render_template(
                "journal/add_entry.html",
                plant=plant,
                action_types=journal_service.ACTION_TYPE_NAMES,
            )

        # Create journal entry
        action, error = journal_service.create_plant_action(
            user_id=user_id,
            plant_id=plant_id,
            action_type=action_type,
            notes=notes or None,
            amount_ml=amount_ml,
            photo_url=photo_url,
            photo_url_thumb=photo_url_thumb,
        )

        if error:
            flash(f"Error creating journal entry: {error}", "error")
            return render_template(
                "journal/add_entry.html",
                plant=plant,
                action_types=journal_service.ACTION_TYPE_NAMES,
            )

        # Track analytics event
        analytics.track_event(
            user_id,
            analytics.EVENT_JOURNAL_ENTRY_CREATED,
            {
                "action_id": action["id"],
                "plant_id": plant_id,
                "action_type": action_type
            }
        )

        # Check for watering streak milestone
        from app.services.marketing_emails import check_watering_streak
        check_watering_streak(user_id)

        action_name = journal_service.ACTION_TYPE_NAMES.get(action_type, action_type)
        flash(f"✓ {action_name} logged for {plant['name']}!", "success")
        return redirect(url_for("journal.view_plant_journal", plant_id=plant_id))

    # GET request - show form
    return render_template(
        "journal/add_entry.html",
        plant=plant,
        action_types=journal_service.ACTION_TYPE_NAMES,
    )


@journal_bp.route("/recent")
@require_auth
def recent_activity():
    """View recent activity across all plants."""
    user_id = get_current_user_id()

    days = request.args.get("days", 7, type=int)
    if days < 1 or days > 90:
        days = 7

    actions = journal_service.get_recent_actions(user_id, days=days)

    return render_template(
        "journal/recent_activity.html",
        actions=actions,
        days=days,
        action_type_names=journal_service.ACTION_TYPE_NAMES,
        action_type_emojis=journal_service.ACTION_TYPE_EMOJIS,
    )


@journal_bp.route("/entry/<action_id>/delete", methods=["POST"])
@require_auth
def delete_entry(action_id):
    """Delete a journal entry."""
    # Validate UUID format before database query
    if not is_valid_uuid(action_id):
        flash("Invalid entry ID.", "error")
        return redirect(url_for("dashboard.index"))

    user_id = get_current_user_id()

    # Get action to find plant_id and photo_url
    action = journal_service.get_action_by_id(action_id, user_id)
    if not action:
        flash("Journal entry not found.", "error")
        return redirect(url_for("dashboard.index"))

    plant_id = action.get("plant_id")

    # Delete all photo versions if they exist (consolidated helper)
    delete_all_photo_versions(action, delete_func=delete_plant_photo)

    # Delete action
    success, error = journal_service.delete_action(action_id, user_id)

    if not success:
        flash(f"Error deleting entry: {error}", "error")
    else:
        flash("Journal entry deleted successfully.", "success")

    return redirect(url_for("journal.view_plant_journal", plant_id=plant_id))


# Quick log API endpoint (for AJAX from dashboard/plant pages)
@journal_bp.route("/api/quick-log", methods=["POST"])
@require_auth
def api_quick_log():
    """
    Quick log an action via JSON API.

    Security: CSRF token required via X-CSRFToken header
    (automatically validated by Flask-WTF CSRFProtect)

    Request body:
        {
            "plant_id": "uuid",
            "action_type": "water|fertilize|note",
            "notes": "optional notes",
            "amount_ml": 100 (optional)
        }
    """
    user_id = get_current_user_id()

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Invalid request"}), 400

        plant_id = data.get("plant_id")
        action_type = data.get("action_type")
        notes = data.get("notes")
        amount_ml = data.get("amount_ml")

        if not plant_id or not action_type:
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        # Validate UUID format before database query
        if not is_valid_uuid(plant_id):
            return jsonify({"success": False, "error": "Invalid plant ID format"}), 400

        # Verify plant ownership
        plant = get_plant_by_id(plant_id, user_id)
        if not plant:
            return jsonify({"success": False, "error": "Plant not found"}), 404

        # Create action
        action, error = journal_service.create_plant_action(
            user_id=user_id,
            plant_id=plant_id,
            action_type=action_type,
            notes=notes,
            amount_ml=amount_ml,
        )

        if error:
            current_app.logger.error(f"Quick-log action failed: {error}")
            return jsonify({"success": False, "error": "Failed to log action. Please try again."}), 400

        # Check for watering streak milestone
        from app.services.marketing_emails import check_watering_streak
        check_watering_streak(user_id)

        return jsonify({
            "success": True,
            "message": f"{journal_service.ACTION_TYPE_NAMES.get(action_type)} logged",
            "action": action,
        })

    except Exception as e:
        # Log the actual error for debugging
        sanitized_msg = sanitize_error(e, "database", "API quick-log failed")
        return jsonify({"success": False, "error": sanitized_msg}), 500
