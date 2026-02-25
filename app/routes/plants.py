"""
Plants management routes.

Handles:
- Plant listing (grid view)
- Adding new plants with photo upload
- Viewing/editing individual plants
- Plant deletion with photo cleanup
"""

from __future__ import annotations
from flask import Blueprint, render_template, flash, redirect, url_for, request, current_app, jsonify
from werkzeug.utils import secure_filename
from app.utils.auth import require_auth, get_current_user_id
from app.utils.photo_handler import handle_photo_upload, delete_all_photo_versions
from app.utils.file_upload import validate_upload_file
from app.utils.validation import is_valid_uuid
from app.services import supabase_client
from app.services import analytics
from app.extensions import limiter


plants_bp = Blueprint("plants", __name__, url_prefix="/plants")


@plants_bp.route("/")
@require_auth
def index():
    """Plant library - list all user's plants in grid view."""
    user_id = get_current_user_id()

    plants = supabase_client.get_user_plants(user_id)
    plant_count = len(plants)

    return render_template(
        "plants/index.html",
        plants=plants,
        plant_count=plant_count
    )


@plants_bp.route("/add", methods=["GET", "POST"])
@require_auth
@limiter.limit(lambda: current_app.config['UPLOAD_RATE_LIMIT'])
def add():
    """Add a new plant to the user's collection."""
    user_id = get_current_user_id()

    # Redirect first-time users to onboarding
    plants = supabase_client.get_user_plants(user_id)
    if not plants or len(plants) == 0:
        # Check if onboarding is incomplete
        profile = supabase_client.get_user_profile(user_id)
        if profile and not profile.get("onboarding_completed", False):
            return redirect(url_for("plants.onboarding"))

    # Check if user can add more plants
    can_add, message = supabase_client.can_add_plant(user_id)
    if not can_add:
        flash(message, "warning")
        return redirect(url_for("plants.index"))

    if request.method == "POST":
        # Get form data
        name = request.form.get("name", "").strip()
        species = request.form.get("species", "").strip()
        nickname = request.form.get("nickname", "").strip()
        location = request.form.get("location", "").strip()
        light = request.form.get("light", "").strip()
        notes = request.form.get("notes", "").strip()

        # Get initial assessment fields (optional)
        initial_health_state = request.form.get("initial_health_state", "").strip()
        ownership_duration = request.form.get("ownership_duration", "").strip()
        current_watering_schedule = request.form.get("current_watering_schedule", "").strip()
        initial_concerns = request.form.get("initial_concerns", "").strip()

        # Validation
        if not name:
            flash("Plant name is required.", "error")
            return render_template("plants/add.html")

        # Handle photo upload (consolidated helper)
        file = request.files.get("photo")
        photo_url, photo_url_thumb = handle_photo_upload(file, user_id)

        # If upload failed with error, return early
        if file and file.filename and not photo_url:
            return render_template("plants/add.html")

        # Create plant
        plant_data = {
            "name": name,
            "species": species,
            "nickname": nickname,
            "location": location,
            "light": light,
            "notes": notes,
            "photo_url": photo_url,
            "photo_url_thumb": photo_url_thumb if photo_url else None,
            # Initial assessment fields (for AI context and progress tracking)
            "initial_health_state": initial_health_state,
            "ownership_duration": ownership_duration,
            "current_watering_schedule": current_watering_schedule,
            "initial_concerns": initial_concerns
        }

        plant = supabase_client.create_plant(user_id, plant_data)
        if plant:
            # Track analytics event
            analytics.track_event(
                user_id,
                analytics.EVENT_PLANT_ADDED,
                {"plant_id": plant["id"], "plant_name": name}
            )

            # Check for milestone emails
            from app.services.marketing_emails import (
                trigger_milestone_event,
                MILESTONE_FIRST_PLANT,
                MILESTONE_COLLECTION_5
            )

            # Get updated plant count
            updated_plants = supabase_client.get_user_plants(user_id)
            plant_count = len(updated_plants) if updated_plants else 1

            # First plant milestone
            if plant_count == 1:
                trigger_milestone_event(user_id, MILESTONE_FIRST_PLANT, event_key="once")


            # Collection milestones (5, 10, 25, 50, etc.)
            if plant_count in [5, 10, 25, 50, 100]:
                trigger_milestone_event(
                    user_id,
                    MILESTONE_COLLECTION_5,
                    {"plant_count": plant_count},
                    event_key=f"count:{plant_count}"
                )

            flash(f"🌱 {name} added successfully!", "success")
            return redirect(url_for("plants.view", plant_id=plant["id"]))
        else:
            flash("Failed to add plant. Please try again.", "error")

    return render_template("plants/add.html")


@plants_bp.route("/<plant_id>")
@require_auth
def view(plant_id):
    """View a single plant's details with journal entries."""
    # Validate UUID format before database query
    if not is_valid_uuid(plant_id):
        flash("Invalid plant ID.", "error")
        return redirect(url_for("plants.index"))

    user_id = get_current_user_id()

    plant = supabase_client.get_plant_by_id(plant_id, user_id)
    if not plant:
        flash("Plant not found.", "error")
        return redirect(url_for("plants.index"))

    # Get journal data
    from app.services import journal as journal_service
    recent_actions = journal_service.get_plant_actions(plant_id, user_id, limit=5)
    stats = journal_service.get_action_stats(plant_id, user_id)

    # Get active reminders for this plant
    from app.services import reminders as reminder_service
    plant_reminders = reminder_service.get_user_reminders(
        user_id, plant_id=plant_id, active_only=True
    )

    return render_template(
        "plants/view.html",
        plant=plant,
        recent_actions=recent_actions,
        stats=stats,
        action_type_names=journal_service.ACTION_TYPE_NAMES,
        action_type_emojis=journal_service.ACTION_TYPE_EMOJIS,
        plant_reminders=plant_reminders,
        reminder_type_names=reminder_service.REMINDER_TYPE_NAMES,
    )


@plants_bp.route("/<plant_id>/edit", methods=["GET", "POST"])
@require_auth
@limiter.limit(lambda: current_app.config['UPLOAD_RATE_LIMIT'])
def edit(plant_id):
    """Edit plant information."""
    # Validate UUID format before database query
    if not is_valid_uuid(plant_id):
        flash("Invalid plant ID.", "error")
        return redirect(url_for("plants.index"))

    user_id = get_current_user_id()

    plant = supabase_client.get_plant_by_id(plant_id, user_id)
    if not plant:
        flash("Plant not found.", "error")
        return redirect(url_for("plants.index"))

    if request.method == "POST":
        # Get form data
        name = request.form.get("name", "").strip()
        species = request.form.get("species", "").strip()
        nickname = request.form.get("nickname", "").strip()
        location = request.form.get("location", "").strip()
        light = request.form.get("light", "").strip()
        notes = request.form.get("notes", "").strip()

        # Validation
        if not name:
            flash("Plant name is required.", "error")
            return render_template("plants/edit.html", plant=plant)

        # Handle photo upload - keep existing photos by default
        photo_url = plant.get("photo_url")
        photo_url_thumb = plant.get("photo_url_thumb")

        # Check if user wants to delete current photo
        delete_photo = request.form.get("delete_photo") == "true"
        if delete_photo and photo_url:
            # Delete all photo versions (display, thumbnail)
            current_app.logger.info(f"Photo URLs to delete: display={bool(photo_url)}, thumb={bool(photo_url_thumb)}")
            old_photo_obj = {
                "photo_url": photo_url,
                "photo_url_thumb": photo_url_thumb,
                # Include original URL for backwards compatibility (if it exists in database)
                "photo_url_original": plant.get("photo_url_original")
            }
            delete_all_photo_versions(old_photo_obj)

            # Clear photo URLs
            photo_url = None
            photo_url_thumb = None

        file = request.files.get("photo")
        is_valid, error, file_bytes = validate_upload_file(file)

        if error:  # Validation failed
            flash(error, "error")
            return render_template("plants/edit.html", plant=plant)

        if is_valid and file_bytes:  # New photo provided and valid
            # Upload new photo with optimized versions
            new_photo_urls, upload_error = supabase_client.upload_plant_photo_versions(
                file_bytes,
                user_id,
                secure_filename(file.filename)
            )

            if upload_error:
                # Show specific error message and return early (don't update plant)
                flash(f"Photo upload failed: {upload_error}", "error")
                return render_template("plants/edit.html", plant=plant)
            elif new_photo_urls:
                # Delete old photos if they exist (consolidated helper)
                old_photo_obj = {
                    "photo_url": photo_url,
                    "photo_url_thumb": photo_url_thumb,
                    # Include original URL for backwards compatibility (if it exists in database)
                    "photo_url_original": plant.get("photo_url_original")
                }
                delete_all_photo_versions(old_photo_obj)

                # Set new photo URLs
                photo_url = new_photo_urls['display']
                photo_url_thumb = new_photo_urls['thumbnail']
            else:
                # Fallback error (shouldn't happen, but just in case)
                flash("Failed to upload new photo.", "error")
                return render_template("plants/edit.html", plant=plant)

        # Update plant
        plant_data = {
            "name": name,
            "species": species,
            "nickname": nickname,
            "location": location,
            "light": light,
            "notes": notes,
            "photo_url": photo_url,
            "photo_url_thumb": photo_url_thumb
        }

        updated_plant = supabase_client.update_plant(plant_id, user_id, plant_data)
        if updated_plant:
            flash(f"✨ {name} updated successfully!", "success")
            return redirect(url_for("plants.view", plant_id=plant_id))
        else:
            flash("Failed to update plant. Please try again.", "error")

    return render_template("plants/edit.html", plant=plant)


@plants_bp.route("/<plant_id>/delete", methods=["POST"])
@require_auth
def delete(plant_id):
    """Delete a plant from the user's collection."""
    # Validate UUID format before database query
    if not is_valid_uuid(plant_id):
        flash("Invalid plant ID.", "error")
        return redirect(url_for("plants.index"))

    user_id = get_current_user_id()

    plant = supabase_client.get_plant_by_id(plant_id, user_id)
    if not plant:
        flash("Plant not found.", "error")
        return redirect(url_for("plants.index"))

    plant_name = plant.get("name", "Plant")

    # Delete all photo versions if they exist (consolidated helper)
    delete_all_photo_versions(plant)

    # Delete plant
    if supabase_client.delete_plant(plant_id, user_id):
        flash(f"🗑️ {plant_name} removed from your collection.", "success")
    else:
        flash("Failed to delete plant. Please try again.", "error")

    return redirect(url_for("plants.index"))


@plants_bp.route("/onboarding", methods=["GET", "POST"])
@require_auth
def onboarding():
    """
    First-plant onboarding wizard.

    GET: Display the 3-step wizard
    POST: Handle step 2 (plant creation) and step 3 (reminder creation)
    """
    user_id = get_current_user_id()

    if request.method == "GET":
        # Check if user already has plants - skip onboarding if they do
        plants = supabase_client.get_user_plants(user_id)
        if plants and len(plants) > 0:
            flash("You've already added plants! Welcome back.", "info")
            return redirect(url_for("dashboard.index"))

        # Get user profile to check marketing opt-in status
        profile = supabase_client.get_user_profile(user_id)
        marketing_opt_in = profile.get("marketing_opt_in", False) if profile else False

        return render_template(
            "plants/onboarding.html", marketing_opt_in=marketing_opt_in
        )

    # POST request - handle step submission
    step = request.form.get("step", "3")

    if step == "3":
        # Step 3: Create plant (and save user preferences)
        name = request.form.get("name", "").strip()
        nickname = request.form.get("nickname", "").strip()
        location = request.form.get("location", "indoor_potted").strip()
        light = request.form.get("light", "").strip()

        # Get user preferences from hidden fields (captured in step 2)
        experience_level = request.form.get("experience_level", "").strip()
        primary_goal = request.form.get("primary_goal", "").strip()
        time_commitment = request.form.get("time_commitment", "").strip()
        environment_preference = request.form.get("environment_preference", "").strip()

        # Save user preferences if any were provided
        if experience_level or primary_goal or time_commitment or environment_preference:
            supabase_client.update_user_preferences(
                user_id,
                experience_level=experience_level,
                primary_goal=primary_goal,
                time_commitment=time_commitment,
                environment_preference=environment_preference
            )

        # Validation
        if not name:
            return jsonify({"success": False, "message": "Plant name is required."}), 400

        # Handle photo upload
        photo_url = None
        photo_url_thumb = None
        file = request.files.get("photo")

        if file and file.filename:
            is_valid, error, file_bytes = validate_upload_file(file)

            if error:
                return jsonify({"success": False, "message": error}), 400

            if is_valid and file_bytes:
                photo_urls, upload_error = supabase_client.upload_plant_photo_versions(
                    file_bytes,
                    user_id,
                    secure_filename(file.filename)
                )

                if upload_error:
                    current_app.logger.error(f"Photo upload failed: {upload_error}")
                    return jsonify({"success": False, "message": "Photo upload failed. Please try again."}), 400
                elif photo_urls:
                    photo_url = photo_urls['display']
                    photo_url_thumb = photo_urls['thumbnail']

        # Create plant
        plant_data = {
            "name": name,
            "nickname": nickname,
            "location": location,
            "light": light,
            "photo_url": photo_url,
            "photo_url_thumb": photo_url_thumb if photo_url else None
        }

        plant = supabase_client.create_plant(user_id, plant_data)

        if plant:
            # Track first plant event
            analytics.track_event(
                user_id,
                analytics.EVENT_FIRST_PLANT_ADDED,
                {"plant_id": plant["id"], "plant_name": name}
            )

            # Trigger first plant milestone email
            from app.services.marketing_emails import (
                trigger_milestone_event,
                MILESTONE_FIRST_PLANT
            )
            trigger_milestone_event(user_id, MILESTONE_FIRST_PLANT, event_key="once")

            # Handle marketing opt-in from onboarding (if user opted in during Step 1)
            marketing_opt_in = request.form.get("marketing_opt_in") == "on"
            if marketing_opt_in:
                supabase_client.update_marketing_preference(user_id, marketing_opt_in=True)

            # Return JSON response for AJAX call
            return jsonify({
                "success": True,
                "plant_id": plant["id"],
                "message": f"{name} added successfully!"
            })
        else:
            return jsonify({
                "success": False,
                "message": "Failed to create plant. Please try again."
            }), 500

    elif step == "4":
        # Step 4: Create reminder and complete onboarding
        watering_frequency = request.form.get("watering_frequency", "").strip()
        skip_reminder = request.form.get("skip_reminder") == "on"

        # Get the plant_id from the previous step (should be in session or passed as hidden field)
        # For now, get the user's most recent plant
        plants = supabase_client.get_user_plants(user_id)
        if not plants or len(plants) == 0:
            flash("No plant found. Please start over.", "error")
            return redirect(url_for("plants.onboarding"))

        plant = plants[0]  # Most recent plant
        plant_id = plant["id"]
        plant_name = plant["name"]

        # Create reminder if not skipped
        if not skip_reminder and watering_frequency:
            from app.services import reminders as reminder_service

            reminder_data = {
                "user_id": user_id,
                "plant_id": plant_id,
                "reminder_type": "watering",
                "title": f"Water {plant_name}",
                "frequency": watering_frequency,
                "skip_weather_adjustment": False
            }

            reminder, error = reminder_service.create_reminder(**reminder_data)

            if reminder:
                analytics.track_event(
                    user_id,
                    analytics.EVENT_REMINDER_CREATED,
                    {
                        "reminder_id": reminder["id"],
                        "reminder_type": "watering",
                        "frequency": watering_frequency
                    }
                )

        # Mark onboarding as complete
        supabase_client.mark_onboarding_complete(user_id)

        flash(f"🎉 Welcome to PlantCareAI! Your plant {plant_name} is all set up.", "success")
        return redirect(url_for("plants.view", plant_id=plant_id))

    # Invalid step
    flash("Invalid request.", "error")
    return redirect(url_for("plants.onboarding"))


@plants_bp.route("/onboarding/skip", methods=["POST"])
@require_auth
def onboarding_skip():
    """Skip onboarding and mark it as complete without creating a plant."""
    user_id = get_current_user_id()

    # Mark onboarding as complete
    supabase_client.mark_onboarding_complete(user_id)

    flash("You can add your first plant anytime from the dashboard!", "info")
    return redirect(url_for("dashboard.index"))
