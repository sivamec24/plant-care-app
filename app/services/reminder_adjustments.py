"""
Reminder Adjustment Engine - Weather-aware reminder adjustments.

Evaluates weather conditions, plant characteristics, and seasonal patterns
to determine if reminders should be automatically adjusted or suggested for review.

Priority Order (Safety → Precipitation → Plant stress → Seasonal → Light):
1. Safety (freeze warnings, extreme heat) - highest priority
2. Precipitation (rain/snow affecting watering)
3. Plant stress indicators
4. Seasonal dormancy
5. Light adjustments
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import date, datetime, timedelta, timezone
from flask import current_app, has_app_context

from .weather import (
    get_weather_for_city,
    get_precipitation_forecast_24h,
    get_temperature_extremes_forecast,
    get_seasonal_pattern
)
from .plant_intelligence import (
    infer_plant_characteristics,
    get_light_adjustment_factor
)


# Adjustment actions
ACTION_POSTPONE = "postpone"
ACTION_ADVANCE = "advance"
ACTION_SKIP = "skip"
ACTION_NONE = "none"

# Adjustment modes
MODE_AUTOMATIC = "automatic"  # Apply automatically
MODE_SUGGESTION = "suggestion"  # Suggest for user review

# Priority levels for conflict resolution
PRIORITY_SAFETY = 1  # Freeze warnings, extreme heat
PRIORITY_PRECIPITATION = 2  # Heavy rain, snow
PRIORITY_PLANT_STRESS = 3  # Plant stress indicators
PRIORITY_SEASONAL = 4  # Dormancy, seasonal changes
PRIORITY_LIGHT = 5  # Light-based adjustments


def _get_config(key: str, default: Any) -> Any:
    """
    Get configuration value with fallback.

    Args:
        key: Config key name
        default: Default value if not configured

    Returns:
        Configuration value
    """
    if has_app_context():
        from app.config import BaseConfig
        return getattr(BaseConfig, key, default)
    return default


def evaluate_reminder_adjustment(
    reminder: Dict[str, Any],
    plant: Dict[str, Any],
    user_city: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluate whether a reminder should be adjusted based on weather and plant characteristics.

    Returns adjustment recommendation with reasoning, or None if no adjustment needed.

    Adjustment types by plant location:
    - OUTDOOR plants: All adjustments (weather, seasonal, light)
    - INDOOR plants: Seasonal dormancy and light adjustments only
      (no freeze, rain, extreme heat, or outdoor temperature adjustments)

    Args:
        reminder: Reminder dict with type, next_due, skip_weather_adjustment, etc.
        plant: Plant dict with location, species, notes, etc.
        user_city: Optional city for weather data

    Returns:
        Dict with adjustment details:
        {
            "action": "postpone|advance|skip|none",
            "mode": "automatic|suggestion",
            "days": 2,  # Days to adjust (positive = postpone, negative = advance)
            "reason": "Heavy rain expected (0.8 inches)",
            "priority": 2,  # Priority level for conflict resolution
            "details": {
                "weather_condition": "heavy_rain",
                "precipitation_inches": 0.8,
                "temp_min_f": 35,
                "freeze_risk": False
            }
        }
        Or {"action": "none"} if no adjustment needed

    Example:
        >>> reminder = {"reminder_type": "watering", "next_due": "2025-12-03"}
        >>> plant = {"location": "outdoor_bed", "species": "Tomato"}
        >>> result = evaluate_reminder_adjustment(reminder, plant, "Seattle, WA")
        >>> print(result)
        {"action": "postpone", "mode": "automatic", "days": 2, "reason": "Heavy rain expected"}
    """
    # Check if adjustments enabled
    if not _get_config("WEATHER_REMINDER_ADJUSTMENTS_ENABLED", True):
        return {"action": ACTION_NONE}

    # Check if this reminder opts out of weather adjustments
    if reminder.get("skip_weather_adjustment", False):
        return {"action": ACTION_NONE}

    # Check if reminder already has a weather adjustment applied
    # Allow re-evaluation only if the reminder is due today (weather may have changed)
    if reminder.get("weather_adjusted_due"):
        adjusted_due = reminder.get("weather_adjusted_due")
        if isinstance(adjusted_due, str):
            adjusted_due = datetime.fromisoformat(adjusted_due).date()

        # If adjusted date is in the future, skip (reminder already postponed, not due yet)
        if adjusted_due > date.today():
            return {"action": ACTION_NONE}
        # If adjusted date is today or past, continue evaluation (may need another adjustment)

    # Only adjust watering and misting reminders for now
    reminder_type = reminder.get("reminder_type", "")
    if reminder_type not in ["watering", "misting"]:
        return {"action": ACTION_NONE}

    # Determine if plant is outdoor (affects which adjustments apply)
    # Indoor plants get seasonal/light adjustments but not weather-specific ones
    plant_location = plant.get("location") or "indoor_potted"
    is_outdoor = "outdoor" in plant_location.lower()

    # Parse next_due for later use (adjust ALL active reminders regardless of due date)
    next_due = reminder.get("next_due")
    if next_due and isinstance(next_due, str):
        next_due = datetime.fromisoformat(next_due).date()

    # Get weather data
    if not user_city:
        return {"action": ACTION_NONE}  # Can't adjust without weather

    weather = get_weather_for_city(user_city)
    if not weather:
        return {"action": ACTION_NONE}  # Weather unavailable

    # Get precipitation forecast
    precip_forecast = get_precipitation_forecast_24h(user_city)

    # Get temperature extremes
    temp_extremes = get_temperature_extremes_forecast(user_city, hours=48)

    # Get seasonal pattern
    seasonal = get_seasonal_pattern(user_city)

    # Get plant characteristics and light adjustments
    plant_chars = infer_plant_characteristics(plant, user_city)
    light_factor = get_light_adjustment_factor(plant, weather, seasonal)

    # Collect all potential adjustments with priorities
    adjustments = []

    # ========== OUTDOOR-ONLY ADJUSTMENTS ==========
    # These weather-specific adjustments only apply to outdoor plants
    if is_outdoor:
        # PRIORITY 1: SAFETY - Freeze warnings
        if temp_extremes and temp_extremes.get("freeze_risk"):
            temp_min = temp_extremes.get("temp_min_f", 32)

            # Postpone watering before freeze
            if reminder_type == "watering":
                adjustments.append({
                    "action": ACTION_POSTPONE,
                    "mode": MODE_AUTOMATIC,
                    "days": 2,
                    "reason": f"Freeze warning: Low of {temp_min:.0f}°F expected. Avoid watering before freeze.",
                    "priority": PRIORITY_SAFETY,
                    "details": {
                        "weather_condition": "freeze_warning",
                        "temp_min_f": temp_min,
                        "freeze_risk": True
                    }
                })

        # PRIORITY 1: SAFETY - Extreme heat (tender plants)
        if weather and weather.get("temp_f", 0) > _get_config("WEATHER_ADJUSTMENT_EXTREME_HEAT_THRESHOLD", 95):
            # Check if plant is tender
            if plant_chars.get("cold_tolerance") == "tender":
                temp_f = weather.get("temp_f")
                adjustments.append({
                    "action": ACTION_ADVANCE,
                    "mode": MODE_SUGGESTION,  # Suggest, don't auto-adjust
                    "days": -1,
                    "reason": f"Extreme heat ({temp_f:.0f}°F). Tender plants may need extra water.",
                    "priority": PRIORITY_SAFETY,
                    "details": {
                        "weather_condition": "extreme_heat",
                        "temp_f": temp_f,
                        "plant_tolerance": "tender"
                    }
                })

        # PRIORITY 2: PRECIPITATION - Heavy rain
        if precip_forecast is not None and precip_forecast > 0:
            heavy_rain_threshold = _get_config("WEATHER_ADJUSTMENT_RAIN_THRESHOLD_HEAVY", 0.5)
            light_rain_threshold = _get_config("WEATHER_ADJUSTMENT_RAIN_THRESHOLD_LIGHT", 0.25)

            if precip_forecast >= heavy_rain_threshold:
                # Heavy rain - automatic postpone
                adjustments.append({
                    "action": ACTION_POSTPONE,
                    "mode": MODE_AUTOMATIC,
                    "days": 2,
                    "reason": f"Heavy rain expected ({precip_forecast:.1f} inches). Soil will be saturated.",
                    "priority": PRIORITY_PRECIPITATION,
                    "details": {
                        "weather_condition": "heavy_rain",
                        "precipitation_inches": precip_forecast
                    }
                })
            elif precip_forecast >= light_rain_threshold:
                # Light rain - suggestion
                adjustments.append({
                    "action": ACTION_POSTPONE,
                    "mode": MODE_SUGGESTION,
                    "days": 1,
                    "reason": f"Light rain expected ({precip_forecast:.1f} inches). May be able to skip watering.",
                    "priority": PRIORITY_PRECIPITATION,
                    "details": {
                        "weather_condition": "light_rain",
                        "precipitation_inches": precip_forecast
                    }
                })

        # PRIORITY 3: PLANT STRESS - Water needs vs outdoor weather
        if plant_chars and weather:
            water_needs = plant_chars.get("water_needs", "moderate")
            humidity = weather.get("humidity", 50)
            temp_f = weather.get("temp_f", 70)

            # High water need plant + hot dry weather = suggest advance
            if water_needs == "high" and temp_f > 85 and humidity < 40:
                adjustments.append({
                    "action": ACTION_ADVANCE,
                    "mode": MODE_SUGGESTION,
                    "days": -1,
                    "reason": f"Hot, dry weather ({temp_f:.0f}°F, {humidity}% humidity). High-water plant may need earlier watering.",
                    "priority": PRIORITY_PLANT_STRESS,
                    "details": {
                        "weather_condition": "hot_dry",
                        "temp_f": temp_f,
                        "humidity": humidity,
                        "water_needs": "high"
                    }
                })

            # Low water need plant + cool humid weather = suggest postpone
            if water_needs == "low" and temp_f < 65 and humidity > 60:
                adjustments.append({
                    "action": ACTION_POSTPONE,
                    "mode": MODE_SUGGESTION,
                    "days": 1,
                    "reason": f"Cool, humid weather ({temp_f:.0f}°F, {humidity}% humidity). Low-water plant can wait.",
                    "priority": PRIORITY_PLANT_STRESS,
                    "details": {
                        "weather_condition": "cool_humid",
                        "temp_f": temp_f,
                        "humidity": humidity,
                        "water_needs": "low"
                    }
                })

    # ========== ALL PLANTS (indoor + outdoor) ==========
    # These adjustments apply to all plants regardless of location

    # PRIORITY 4: SEASONAL - Dormancy period
    if seasonal and seasonal.get("is_dormancy_period") and plant_chars:
        lifecycle = plant_chars.get("lifecycle", "unknown")

        # Perennial plants in dormancy need less water
        if lifecycle == "perennial":
            adjustments.append({
                "action": ACTION_POSTPONE,
                "mode": MODE_SUGGESTION,
                "days": 2,
                "reason": f"Plant is in dormancy period ({seasonal.get('season')}). Reduce watering frequency.",
                "priority": PRIORITY_SEASONAL,
                "details": {
                    "weather_condition": "dormancy",
                    "season": seasonal.get("season"),
                    "lifecycle": lifecycle
                }
            })

    # PRIORITY 5: LIGHT - Seasonal light adjustments
    if light_factor != 1.0:
        if light_factor < 0.9:
            # Reduced light = less water needed
            days_adjust = 1 if light_factor < 0.8 else 0
            if days_adjust > 0:
                adjustments.append({
                    "action": ACTION_POSTPONE,
                    "mode": MODE_SUGGESTION,
                    "days": days_adjust,
                    "reason": f"Reduced light levels. Plant needs {int((1 - light_factor) * 100)}% less water.",
                    "priority": PRIORITY_LIGHT,
                    "details": {
                        "weather_condition": "reduced_light",
                        "light_factor": light_factor
                    }
                })
        elif light_factor > 1.1:
            # Increased light = more water needed
            days_adjust = -1 if light_factor > 1.2 else 0
            if days_adjust < 0:
                adjustments.append({
                    "action": ACTION_ADVANCE,
                    "mode": MODE_SUGGESTION,
                    "days": days_adjust,
                    "reason": f"High light levels. Plant may need {int((light_factor - 1) * 100)}% more water.",
                    "priority": PRIORITY_LIGHT,
                    "details": {
                        "weather_condition": "high_light",
                        "light_factor": light_factor
                    }
                })

    # CONFLICT RESOLUTION: Select highest priority adjustment
    if not adjustments:
        return {"action": ACTION_NONE}

    # Sort by priority (lower number = higher priority)
    adjustments.sort(key=lambda x: x["priority"])

    # Return highest priority adjustment
    return adjustments[0]


def apply_automatic_adjustments(
    reminders: List[Dict[str, Any]],
    plants_by_id: Dict[str, Dict[str, Any]],
    user_city: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Apply automatic adjustments to a list of reminders.

    Only applies adjustments with mode="automatic". Suggestion-mode adjustments
    are returned separately for user review.

    When automatic adjustments are applied:
    - Saves the adjustment to the database (weather_adjusted_due, weather_adjustment_reason)
    - Reminders adjusted to a future date are EXCLUDED from the returned list
      (they're no longer due today)
    - Reminders adjusted to today are included with adjustment info

    Args:
        reminders: List of reminder dicts
        plants_by_id: Dict mapping plant_id to plant data
        user_city: Optional city for weather data

    Returns:
        List of reminders still due today (after automatic adjustments applied):
        - Reminders with no adjustment needed
        - Reminders adjusted to today (with adjustment info)
        - EXCLUDES reminders adjusted to future dates

    Example:
        >>> reminders = [{"id": "r1", "plant_id": "p1", "next_due": "2025-12-03"}]
        >>> plants = {"p1": {"location": "outdoor_bed", "species": "Tomato"}}
        >>> adjusted = apply_automatic_adjustments(reminders, plants, "Seattle, WA")
    """
    from .supabase_client import get_admin_client

    adjusted_reminders = []
    today = date.today()

    for reminder in reminders:
        plant_id = reminder.get("plant_id")
        plant = plants_by_id.get(plant_id)

        if not plant:
            # Can't adjust without plant data
            adjusted_reminders.append(reminder)
            continue

        # Evaluate adjustment
        adjustment_rec = evaluate_reminder_adjustment(reminder, plant, user_city)

        # Only apply automatic adjustments
        if adjustment_rec.get("mode") == MODE_AUTOMATIC and adjustment_rec.get("action") != ACTION_NONE:
            # Calculate adjusted due date
            next_due = reminder.get("next_due")
            if next_due:
                if isinstance(next_due, str):
                    next_due = datetime.fromisoformat(next_due).date()

                days_adjust = adjustment_rec.get("days", 0)
                adjusted_due = next_due + timedelta(days=days_adjust)

                # Ensure adjusted date is at least tomorrow for postponements
                if adjustment_rec["action"] == ACTION_POSTPONE and adjusted_due <= today:
                    adjusted_due = today + timedelta(days=1)

                # Save automatic adjustment to database
                reminder_id = reminder.get("id")
                user_id = reminder.get("user_id")
                if reminder_id and user_id:
                    try:
                        supabase = get_admin_client()
                        if supabase:
                            supabase.table("reminders").update({
                                "weather_adjusted_due": adjusted_due.isoformat(),
                                "weather_adjustment_reason": adjustment_rec["reason"],
                            }).eq("id", reminder_id).eq("user_id", user_id).execute()
                    except Exception:
                        # Don't fail the request if DB update fails
                        pass

                # Only include reminder if adjusted date is today or earlier
                if adjusted_due <= today:
                    reminder_copy = reminder.copy()
                    reminder_copy["adjustment"] = {
                        "action": adjustment_rec["action"],
                        "days": days_adjust,
                        "reason": adjustment_rec["reason"],
                        "adjusted_due_date": adjusted_due.isoformat(),
                        "adjusted_at": datetime.now().isoformat(),
                        "details": adjustment_rec.get("details", {})
                    }
                    adjusted_reminders.append(reminder_copy)
                # Reminders adjusted to future dates are excluded from Today's Tasks
            else:
                adjusted_reminders.append(reminder)
        else:
            # No automatic adjustment
            adjusted_reminders.append(reminder)

    return adjusted_reminders


def create_suggestion_notification(
    reminder: Dict[str, Any],
    adjustment: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Create a user-reviewable suggestion notification.

    These are shown in the UI for user to accept or dismiss.

    Args:
        reminder: Reminder dict
        adjustment: Adjustment recommendation from evaluate_reminder_adjustment()

    Returns:
        Suggestion notification dict:
        {
            "reminder_id": "r123",
            "plant_name": "Tomato Plant",
            "suggestion_type": "postpone_watering",
            "message": "Light rain expected. Consider postponing watering by 1 day.",
            "action_label": "Postpone 1 day",
            "details": {...}
        }
    """
    action = adjustment.get("action", ACTION_NONE)
    days = adjustment.get("days", 0)
    reason = adjustment.get("reason", "")

    # Build friendly message
    plant_name = reminder.get("plant_name", "Your plant")
    reminder_type = reminder.get("reminder_type", "watering")

    if action == ACTION_POSTPONE:
        message = f"{reason} Consider postponing {reminder_type} by {days} day{'s' if abs(days) > 1 else ''}."
        action_label = f"Postpone {days} day{'s' if abs(days) > 1 else ''}"
    elif action == ACTION_ADVANCE:
        message = f"{reason} Consider advancing {reminder_type} by {abs(days)} day{'s' if abs(days) > 1 else ''}."
        action_label = f"Advance {abs(days)} day{'s' if abs(days) > 1 else ''}"
    elif action == ACTION_SKIP:
        message = f"{reason} Consider skipping this {reminder_type}."
        action_label = "Skip this reminder"
    else:
        message = reason
        action_label = "Review"

    return {
        "reminder_id": reminder.get("id"),
        "plant_name": plant_name,
        "suggestion_type": f"{action}_{reminder_type}",
        "message": message,
        "action_label": action_label,
        "days": days,
        "details": adjustment.get("details", {})
    }


def get_adjustment_suggestions(
    reminders: List[Dict[str, Any]],
    plants_by_id: Dict[str, Dict[str, Any]],
    user_city: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get all suggestion-mode adjustments for user review.

    Returns suggestions that require user approval before applying.

    Args:
        reminders: List of reminder dicts
        plants_by_id: Dict mapping plant_id to plant data
        user_city: Optional city for weather data

    Returns:
        List of suggestion notifications

    Example:
        >>> suggestions = get_adjustment_suggestions(reminders, plants, "Seattle, WA")
        >>> for s in suggestions:
        ...     print(s["message"])
    """
    suggestions = []

    for reminder in reminders:
        plant_id = reminder.get("plant_id")
        plant = plants_by_id.get(plant_id)

        if not plant:
            continue

        # Evaluate adjustment
        adjustment_rec = evaluate_reminder_adjustment(reminder, plant, user_city)

        # Only collect suggestions (not automatic)
        if adjustment_rec.get("mode") == MODE_SUGGESTION and adjustment_rec.get("action") != ACTION_NONE:
            suggestion = create_suggestion_notification(reminder, adjustment_rec)
            suggestions.append(suggestion)

    return suggestions


def batch_adjust_all_users_reminders() -> Dict[str, Any]:
    """
    Daily cron job: Adjust reminders for all active users.

    Runs at 6:00 AM daily to update weather adjustments for all users
    with active watering/misting reminders.

    Returns:
        Dict with stats:
        {
            "total_users": 100,
            "users_processed": 85,
            "total_adjusted": 42,
            "errors": 3
        }
    """
    from .supabase_client import get_admin_client
    from .reminders import batch_adjust_reminders_for_weather
    import logging

    logger = logging.getLogger(__name__)
    logger.info("[Weather Adjustments] Starting daily batch adjustment job")

    supabase = get_admin_client()
    stats = {
        "total_users": 0,
        "users_processed": 0,
        "total_adjusted": 0,
        "errors": 0
    }

    try:
        # Get all users with active reminders (optimization query)
        response = supabase.rpc('get_users_with_active_reminders').execute()
        users = response.data or []
        stats["total_users"] = len(users)

        logger.info(f"[Weather Adjustments] Processing {len(users)} users with active reminders")

        for user in users:
            user_id = user.get("user_id")
            if not user_id:
                continue

            try:
                # Get user's profile to fetch city
                profile_response = supabase.table("profiles").select("city").eq("id", user_id).execute()
                profile = profile_response.data[0] if profile_response.data else None
                city = profile.get("city") if profile else None

                if not city:
                    logger.debug(f"[Weather Adjustments] User {user_id} has no city set, skipping")
                    continue

                # Batch adjust reminders for this user
                user_stats = batch_adjust_reminders_for_weather(user_id, city)
                adjusted_count = user_stats.get("adjusted", 0)

                if adjusted_count > 0:
                    logger.info(f"[Weather Adjustments] User {user_id}: {adjusted_count} reminders adjusted")
                    stats["total_adjusted"] += adjusted_count

                stats["users_processed"] += 1

            except Exception as e:
                logger.error(f"[Weather Adjustments] Error processing user {user_id}: {str(e)}")
                stats["errors"] += 1
                continue

        logger.info(
            f"[Weather Adjustments] Completed: "
            f"{stats['users_processed']}/{stats['total_users']} users processed, "
            f"{stats['total_adjusted']} reminders adjusted, "
            f"{stats['errors']} errors"
        )

    except Exception as e:
        logger.error(f"[Weather Adjustments] Batch job failed: {str(e)}")
        stats["errors"] += 1

    return stats
