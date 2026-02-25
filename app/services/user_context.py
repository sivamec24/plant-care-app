"""
User Context Service for AI Integration.

Provides consolidated user plant and reminder context for AI prompts.
Optimized for token efficiency (targeting 500-1200 tokens depending on detail level).

Enhanced with:
- Plant notes and observations
- Care pattern analysis
- Health trend detection
- Weather-aware insights
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from .supabase_client import (
    get_user_plants,
    get_user_profile,
    get_plant_by_id,
    get_user_preferences
)
from .reminders import get_due_reminders, get_upcoming_reminders
from .journal import get_plant_actions, get_plant_actions_batch, get_user_actions
from . import ai_insights
from . import seasonal_context


# ============================================================================
# TIMESTAMP PARSING HELPERS
# ============================================================================

def _parse_date(value) -> Optional[datetime]:
    """Parse a date value, handling both date objects and ISO strings."""
    if value is None:
        return None
    if hasattr(value, 'date'):  # datetime object
        return value.date()
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    return value  # Already a date


def _parse_datetime(value) -> Optional[datetime]:
    """Parse a datetime value, handling ISO strings with Z timezone."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    return None


def get_user_context(user_id: str) -> Dict[str, Any]:
    """
    Assemble concise user context for AI (targeting ~300-500 tokens).

    Includes:
    - All user plants (name, location, light) - concise format
    - Reminders: overdue, due today, next 7 days
    - Recent activities: last 7 days
    - Summary stats

    Args:
        user_id: User UUID

    Returns:
        Dict with plants, reminders, recent_activities, and stats
    """
    # Get all plants (minimal fields for context)
    plants = get_user_plants(user_id, fields="id,name,species,nickname,location,light")

    # Get reminders
    due_today = get_due_reminders(user_id)
    upcoming = get_upcoming_reminders(user_id, days=7)

    # Filter overdue from due_today (those with effective_due_date in past)
    today = datetime.now().date()
    overdue = []
    due_today_filtered = []

    for reminder in due_today:
        effective_due = _parse_date(reminder.get("effective_due_date"))
        if effective_due and effective_due < today:
            overdue.append(_format_reminder_context(reminder))
        else:
            due_today_filtered.append(_format_reminder_context(reminder))

    # Format upcoming reminders with days until
    upcoming_formatted = []
    for reminder in upcoming[:10]:  # Limit to 10 upcoming
        formatted = _format_reminder_context(reminder)

        # Calculate days until
        effective_due = _parse_date(reminder.get("effective_due_date"))
        if effective_due:
            days_until = (effective_due - today).days
            formatted["days_until"] = days_until

        upcoming_formatted.append(formatted)

    # Get recent activities (last 7 days)
    recent_activities = _get_recent_activities_summary(user_id, days=7)

    # Calculate stats
    stats = {
        "total_plants": len(plants),
        "active_reminders": len(due_today) + len(upcoming),
        "overdue_count": len(overdue),
        "due_today_count": len(due_today_filtered)
    }

    return {
        "plants": [_format_plant_context(p) for p in plants],
        "reminders": {
            "overdue": overdue,
            "due_today": due_today_filtered,
            "upcoming_week": upcoming_formatted
        },
        "recent_activities": recent_activities,
        "stats": stats
    }


def get_plant_context(user_id: str, plant_id: str) -> Dict[str, Any]:
    """
    Detailed context for specific plant (targeting ~500-800 tokens).

    Includes:
    - Full plant details
    - Last 14 days of activities (more history for focused query)
    - All active reminders for this plant
    - Plant-specific stats

    Args:
        user_id: User UUID
        plant_id: Plant UUID

    Returns:
        Dict with plant details, activities, reminders, and stats
    """
    # Get plant details
    plant = get_plant_by_id(plant_id, user_id)
    if not plant:
        return {
            "error": "Plant not found or access denied",
            "plant": None,
            "activities": [],
            "reminders": [],
            "stats": {}
        }

    # Get activities for this plant (last 14 days for more context)
    activities = _get_plant_activities_summary(plant_id, user_id, days=14)

    # Get reminders for this plant
    all_reminders = get_due_reminders(user_id) + get_upcoming_reminders(user_id, days=14)
    plant_reminders = [
        _format_reminder_context(r)
        for r in all_reminders
        if r.get("plant_id") == plant_id
    ]

    # Calculate plant-specific stats
    stats = _calculate_plant_stats(plant_id, user_id, activities)

    return {
        "plant": _format_plant_context(plant, detailed=True),
        "activities": activities,
        "reminders": plant_reminders,
        "stats": stats
    }


def _format_plant_context(plant: Dict[str, Any], detailed: bool = False) -> Dict[str, Any]:
    """Format plant data for context (concise or detailed)."""
    if not plant:
        return {}

    base = {
        "id": plant.get("id"),
        "name": plant.get("name"),
        "location": plant.get("location", "indoor_potted"),
    }

    # Add species/nickname if available (helps AI identify plant)
    if plant.get("species"):
        base["species"] = plant["species"]
    if plant.get("nickname"):
        base["nickname"] = plant["nickname"]

    if detailed:
        # Include more fields for plant-specific queries
        if plant.get("light"):
            base["light"] = plant.get("light")
        if plant.get("notes"):
            base["notes"] = plant.get("notes")
        if plant.get("created_at"):
            base["created_at"] = plant.get("created_at")

        # Include initial assessment for baseline context (especially useful
        # for new plants without journal history)
        if plant.get("initial_health_state"):
            base["initial_health"] = plant["initial_health_state"]
        if plant.get("ownership_duration"):
            base["ownership_duration"] = plant["ownership_duration"]
        if plant.get("current_watering_schedule"):
            base["watering_schedule"] = plant["current_watering_schedule"]
        if plant.get("initial_concerns"):
            base["initial_concerns"] = plant["initial_concerns"]
    else:
        # Just light level for general context
        if plant.get("light"):
            base["light"] = plant["light"]

    return base


def _format_reminder_context(reminder: Dict[str, Any]) -> Dict[str, Any]:
    """Format reminder data for context."""
    return {
        "plant_name": reminder.get("plant_name"),
        "type": reminder.get("reminder_type"),
        "title": reminder.get("title"),
        "weather_adjusted": bool(reminder.get("weather_adjustment_reason"))
    }


def _get_recent_activities_summary(user_id: str, days: int = 7) -> List[Dict[str, Any]]:
    """
    Get summary of recent activities across all plants.

    Returns concise list of recent care actions (last N days).

    Performance: Uses single query with JOIN instead of N+1 queries.
    Previous implementation: 1 + N queries (one per plant)
    New implementation: 1 query total (~95% performance improvement for 20+ plants)
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Single optimized query to get all user's activities with plant names
    # This replaces the N+1 pattern of querying each plant individually
    all_activities_raw = get_user_actions(user_id, limit=100)

    # Filter to time window and format
    all_activities = []
    for activity in all_activities_raw:
        action_at = _parse_datetime(activity.get("action_at"))
        if action_at:
            # Only include if within time window
            if action_at >= cutoff_date:
                days_ago = (datetime.now(action_at.tzinfo) - action_at).days
                all_activities.append({
                    "plant_name": activity.get("plant_name", "Unknown"),
                    "action_type": activity.get("action_type"),
                    "days_ago": days_ago,
                    "notes": activity.get("notes")
                })

    # Sort by most recent and limit to 10
    all_activities.sort(key=lambda x: x["days_ago"])
    return all_activities[:10]


def _get_plant_activities_summary(plant_id: str, user_id: str, days: int = 14) -> List[Dict[str, Any]]:
    """
    Get summary of activities for specific plant.

    Returns detailed list of recent care actions for this plant.
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    activities = get_plant_actions(plant_id, user_id, limit=50)

    recent = []
    for activity in activities:
        action_at = _parse_datetime(activity.get("action_at"))
        if action_at and action_at >= cutoff_date:
            days_ago = (datetime.now(action_at.tzinfo) - action_at).days
            recent.append({
                "action_type": activity.get("action_type"),
                "days_ago": days_ago,
                    "amount_ml": activity.get("amount_ml"),
                    "notes": activity.get("notes")
                })

    # Sort by most recent
    recent.sort(key=lambda x: x["days_ago"])
    return recent


def _calculate_plant_stats(plant_id: str, user_id: str, activities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate statistics for specific plant."""
    # Count by action type
    action_counts = {}
    for activity in activities:
        action_type = activity.get("action_type")
        action_counts[action_type] = action_counts.get(action_type, 0) + 1

    # Find last watered
    last_watered_days = None
    for activity in activities:
        if activity.get("action_type") == "water":
            last_watered_days = activity.get("days_ago")
            break

    return {
        "total_activities": len(activities),
        "last_watered_days_ago": last_watered_days,
        "action_counts": action_counts
    }


# ============================================================================
# ENHANCED CONTEXT FUNCTIONS (Tier 2 & 3 - Rich & Diagnostic)
# ============================================================================

def get_enhanced_user_context(
    user_id: str,
    weather: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Enhanced user context with rich plant data and weather awareness (Tier 2 - Default).

    Replaces basic get_user_context() with richer information:
    - Plant notes summary (first 150 chars)
    - Care patterns (watering frequency)
    - Recent observations with health keywords
    - Weather-aware context
    - Health pattern aggregations

    Target: 500-800 tokens (appropriate for default free tier)

    Args:
        user_id: User UUID
        weather: Optional weather dict for weather-aware insights

    Returns:
        Dict with enhanced plants, reminders, observations, patterns, weather_context
    """
    # Get all plants with notes field
    plants = get_user_plants(user_id, fields="id,name,species,nickname,location,light,notes")

    # Get reminders
    due_today = get_due_reminders(user_id)
    upcoming = get_upcoming_reminders(user_id, days=7)

    # Filter overdue from due_today
    today = datetime.now().date()
    overdue = []
    due_today_filtered = []

    for reminder in due_today:
        effective_due = _parse_date(reminder.get("effective_due_date"))
        if effective_due:
            if effective_due < today:
                overdue.append(_format_reminder_context(reminder))
            else:
                due_today_filtered.append(_format_reminder_context(reminder))
        else:
            due_today_filtered.append(_format_reminder_context(reminder))

    # Format upcoming reminders
    upcoming_formatted = []
    for reminder in upcoming[:10]:
        formatted = _format_reminder_context(reminder)
        effective_due = _parse_date(reminder.get("effective_due_date"))
        if effective_due:
            formatted["days_until"] = (effective_due - today).days
        upcoming_formatted.append(formatted)

    # Get recent activities WITH notes (last 7-14 days)
    recent_activities_raw = get_user_actions(user_id, limit=100)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=14)

    activities_with_notes = []
    for activity in recent_activities_raw:
        action_at = _parse_datetime(activity.get("action_at"))
        if action_at and action_at >= cutoff_date:
            days_ago = (datetime.now(action_at.tzinfo) - action_at).days
            note_text = activity.get("notes")

            # Extract keywords if notes present
            keywords = ai_insights.extract_health_keywords(note_text) if note_text else []

            activities_with_notes.append({
                "plant_name": activity.get("plant_name", "Unknown"),
                "action_type": activity.get("action_type"),
                "days_ago": days_ago,
                "notes": note_text[:100] if note_text else None,  # Truncate to 100 chars
                "keywords": keywords
            })

    # Sort and get most recent observations
    recent_observations = ai_insights.summarize_recent_observations(
        activities_with_notes,
        max_observations=3
    )

    # Format plants with enhanced context
    enhanced_plants = []
    for plant in plants[:10]:  # Limit to 10 plants for token budget
        plant_dict = {
            "id": plant.get("id"),
            "name": plant.get("name"),
            "species": plant.get("species"),
            "location": plant.get("location", "indoor_potted"),
            "light": plant.get("light")
        }

        # Add notes (first 500 chars for better context)
        notes = plant.get("notes")
        if notes and notes.strip():
            plant_dict["notes"] = notes[:500]
            if len(notes) > 500:
                plant_dict["notes"] += "..."

        # Calculate watering pattern for this plant
        plant_id = plant.get("id")
        if plant_id:
            plant_activities_raw = get_plant_actions(plant_id, user_id, limit=50)
            plant_activities = []
            for act in plant_activities_raw:
                if act.get("action_type") == "water":
                    plant_activities.append(act)

            pattern = ai_insights.calculate_watering_pattern(plant_activities)
            if pattern.get("avg_interval_days"):
                plant_dict["watering_pattern"] = f"~{pattern['avg_interval_days']}d avg ({pattern['consistency']})"

        enhanced_plants.append(plant_dict)

    # Extract weather context summary if available
    weather_context = None
    if weather:
        weather_context = ai_insights.extract_weather_context_summary(weather)

    # Calculate health patterns across all plants
    all_concerns = set()
    for obs in recent_observations:
        all_concerns.update(obs.get("keywords", []))

    negative_keywords = ["yellow_leaves", "brown_tips", "droopy", "wilting", "pest_spotted", "overwatered"]
    recent_issues = [c for c in all_concerns if c in negative_keywords]

    health_patterns = {
        "plants_with_recent_observations": len([o for o in recent_observations if o.get("note_preview")]),
        "recent_concern_keywords": recent_issues,
        "overall_activity_level": "active" if len(activities_with_notes) >= 5 else "moderate"
    }

    # Calculate stats
    stats = {
        "total_plants": len(plants),
        "active_reminders": len(due_today) + len(upcoming),
        "overdue_count": len(overdue),
        "due_today_count": len(due_today_filtered)
    }

    return {
        "plants": enhanced_plants,
        "reminders": {
            "overdue": overdue,
            "due_today": due_today_filtered,
            "upcoming_week": upcoming_formatted
        },
        "recent_observations": recent_observations,
        "health_patterns": health_patterns,
        "weather_context": weather_context,
        "stats": stats
    }


def get_enhanced_plant_context(
    user_id: str,
    plant_id: str,
    weather: Optional[Dict[str, Any]] = None,
    is_premium: bool = False
) -> Dict[str, Any]:
    """
    Enhanced plant-specific context with optional premium diagnostic features (Tier 2/3).

    Tier 2 (Default): Full plant notes, care patterns, recent observations
    Tier 3 (Premium): + Health trends, comparative insights, extended history

    Target: 500-800 tokens (Tier 2), 800-1200 tokens (Tier 3)

    Args:
        user_id: User UUID
        plant_id: Plant UUID
        weather: Optional weather dict
        is_premium: If True, include premium diagnostic features (Tier 3)

    Returns:
        Dict with enhanced plant details, patterns, insights, weather context
    """
    # Get plant details with all fields
    plant = get_plant_by_id(plant_id, user_id)
    if not plant:
        return {
            "error": "Plant not found or access denied",
            "plant": None,
            "activities": [],
            "reminders": [],
            "patterns": {},
            "stats": {}
        }

    # Get activities (last 14 days for standard, 30 days for premium)
    days = 30 if is_premium else 14
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    activities_raw = get_plant_actions(plant_id, user_id, limit=100)
    activities = []

    for activity in activities_raw:
        action_at = _parse_datetime(activity.get("action_at"))
        if action_at and action_at >= cutoff_date:
            days_ago = (datetime.now(action_at.tzinfo) - action_at).days
            activities.append({
                "action_type": activity.get("action_type"),
                "action_at": activity.get("action_at"),
                "days_ago": days_ago,
                "amount_ml": activity.get("amount_ml"),
                "notes": activity.get("notes")
            })

    # Get reminders for this plant
    all_reminders = get_due_reminders(user_id) + get_upcoming_reminders(user_id, days=14)
    plant_reminders = [
        _format_reminder_context(r)
        for r in all_reminders
        if r.get("plant_id") == plant_id
    ]

    # Calculate care patterns
    watering_pattern = ai_insights.calculate_watering_pattern(activities)

    # Get recent observations
    recent_obs = ai_insights.summarize_recent_observations(activities, max_observations=5)

    # Calculate care completeness
    care_analysis = ai_insights.analyze_care_completeness(
        plant_id,
        activities,
        [r for r in all_reminders if r.get("plant_id") == plant_id]
    )

    # Build plant context
    plant_context = {
        "id": plant.get("id"),
        "name": plant.get("name"),
        "species": plant.get("species"),
        "nickname": plant.get("nickname"),
        "location": plant.get("location"),
        "light": plant.get("light"),
        "notes_full": plant.get("notes")[:500] if plant.get("notes") else None,  # Truncate to 500
        "care_history_summary": {
            "avg_watering_interval_days": watering_pattern.get("avg_interval_days"),
            "watering_consistency": watering_pattern.get("consistency"),
            "watering_trend": watering_pattern.get("recent_trend"),
            "total_activities_period": len(activities),
            "care_level": care_analysis.get("care_level"),
            "on_schedule": care_analysis.get("on_schedule")
        }
    }

    # Add initial assessment (baseline data from when plant was added)
    # This is especially useful for new plants without journal history
    initial_assessment = {}
    if plant.get("initial_health_state"):
        initial_assessment["health_state"] = plant["initial_health_state"]
    if plant.get("ownership_duration"):
        initial_assessment["ownership_duration"] = plant["ownership_duration"]
    if plant.get("current_watering_schedule"):
        initial_assessment["watering_schedule"] = plant["current_watering_schedule"]
    if plant.get("initial_concerns"):
        initial_assessment["concerns"] = plant["initial_concerns"]

    if initial_assessment:
        plant_context["initial_assessment"] = initial_assessment

    # Extract weather context
    weather_context = None
    if weather:
        weather_context = ai_insights.extract_weather_context_summary(weather)

    # Base stats
    stats = {
        "total_activities": len(activities),
        "last_watered_days_ago": watering_pattern.get("avg_interval_days"),
        "care_completion_rate": care_analysis.get("completion_rate"),
        "missed_care_types": care_analysis.get("missed_care_types", [])
    }

    result = {
        "plant": plant_context,
        "activities_detailed": activities[:20],  # Limit to recent 20
        "recent_observations": recent_obs,
        "reminders": plant_reminders,
        "patterns": {
            "watering": watering_pattern,
            "care_level": care_analysis.get("care_level")
        },
        "weather_context": weather_context,
        "stats": stats
    }

    # PREMIUM FEATURES (Tier 3)
    if is_premium:
        # Health trend analysis
        health_trends = ai_insights.identify_health_trends(activities)

        # Comparative insights (vs user's other plants)
        all_user_plants = get_user_plants(user_id, fields="id")
        if len(all_user_plants) > 1:
            # Calculate average watering interval across all plants
            # Use batch fetch to avoid N+1 queries
            other_plant_ids = [p.get("id") for p in all_user_plants if p.get("id") != plant_id]
            all_activities = get_plant_actions_batch(other_plant_ids, user_id, limit_per_plant=50)

            all_intervals = []
            for other_id in other_plant_ids:
                other_activities = all_activities.get(other_id, [])
                other_pattern = ai_insights.calculate_watering_pattern(other_activities)
                if other_pattern.get("avg_interval_days"):
                    all_intervals.append(other_pattern["avg_interval_days"])

            if all_intervals:
                avg_user_interval = sum(all_intervals) / len(all_intervals)
                this_interval = watering_pattern.get("avg_interval_days", avg_user_interval)

                if this_interval < avg_user_interval * 0.8:
                    comparative = "more_frequent_than_others"
                elif this_interval > avg_user_interval * 1.2:
                    comparative = "less_frequent_than_others"
                else:
                    comparative = "similar_to_others"

                result["comparative_insights"] = {
                    "watering_vs_user_avg": comparative,
                    "user_avg_interval": round(avg_user_interval, 1)
                }

        result["health_trends"] = {
            "recent_concerns": health_trends.get("recent_concerns", []),
            "improving": health_trends.get("improving", False),
            "deteriorating": health_trends.get("deteriorating", False),
            "timeline": health_trends.get("timeline", [])
        }

    return result


# ============================================================================
# USER PREFERENCES CONTEXT (For AI Personalization)
# ============================================================================

def get_user_preferences_context(user_id: str) -> Dict[str, Any]:
    """
    Get user's plant care preferences for AI context building.

    Translates preference values into human-readable context for prompts.

    Args:
        user_id: User UUID

    Returns:
        Dict with formatted preference context or empty dict if not configured
    """
    prefs = get_user_preferences(user_id)
    if not prefs or not prefs.get("preferences_completed_at"):
        return {}

    context = {}

    # Experience level context
    experience = prefs.get("experience_level")
    if experience:
        experience_context = {
            "beginner": "new to plant care and learning the basics",
            "intermediate": "has some experience with plants and understands fundamentals",
            "expert": "experienced plant enthusiast with advanced knowledge"
        }
        context["experience_description"] = experience_context.get(experience, experience)
        context["experience_level"] = experience

    # Primary goal context
    goal = prefs.get("primary_goal")
    if goal:
        goal_context = {
            "keep_alive": "focused on keeping plants healthy and not killing them",
            "grow_collection": "interested in expanding their plant collection",
            "specific_focus": "focused on specific plant types or goals"
        }
        context["goal_description"] = goal_context.get(goal, goal)
        context["primary_goal"] = goal

    # Time commitment context
    time = prefs.get("time_commitment")
    if time:
        time_context = {
            "minimal": "has limited time for plant care, prefers low-maintenance plants",
            "moderate": "can dedicate regular time to plant care",
            "dedicated": "enjoys spending significant time on plant care"
        }
        context["time_description"] = time_context.get(time, time)
        context["time_commitment"] = time

    # Environment preference context
    environment = prefs.get("environment_preference")
    if environment:
        env_context = {
            "indoor": "primarily grows indoor plants",
            "outdoor": "primarily grows outdoor plants",
            "both": "grows both indoor and outdoor plants"
        }
        context["environment_description"] = env_context.get(environment, environment)
        context["environment_preference"] = environment

    return context


def get_enhanced_context_for_empty_user(
    user_id: str,
    weather: Optional[Dict[str, Any]] = None,
    forecast: Optional[List[Dict[str, Any]]] = None,
    latitude: float = 40.0
) -> Dict[str, Any]:
    """
    Build enriched context for users without plants or plant data.

    This solves the "cold start" problem by providing value through:
    - User preferences (if configured)
    - Seasonal/timing context
    - Weather-based proactive tips
    - General guidance based on user goals

    Args:
        user_id: User UUID
        weather: Optional current weather data
        forecast: Optional weather forecast data
        latitude: User's latitude for hemisphere detection (default: Northern)

    Returns:
        Dict with preferences, seasonal context, weather tips, and guidance
    """
    # Get user preferences
    preferences = get_user_preferences_context(user_id)

    # Get seasonal context
    season_ctx = seasonal_context.get_seasonal_context(
        latitude=latitude,
        weather=weather,
        forecast=forecast
    )

    # Get timely focus recommendation
    month_ctx = seasonal_context.get_month_context()
    timely_focus = seasonal_context.get_timely_focus(
        season_ctx["season"],
        month_ctx["month_number"]
    )

    # Build guidance based on user goals
    guidance = []
    if preferences.get("primary_goal") == "keep_alive":
        guidance.append("Focus on mastering watering basics - overwatering is the most common mistake")
        guidance.append("Start with forgiving plants like pothos, snake plants, or spider plants")
    elif preferences.get("primary_goal") == "grow_collection":
        guidance.append("Consider plant swaps or propagation to expand affordably")
        guidance.append("Research light and humidity needs before adding new plants")
    elif preferences.get("primary_goal") == "specific_focus":
        guidance.append("Share your specific plant interests for tailored advice")

    if preferences.get("time_commitment") == "minimal":
        guidance.append("Low-maintenance plants like ZZ plant, snake plant, and pothos are great choices")
    elif preferences.get("time_commitment") == "dedicated":
        guidance.append("Consider more demanding plants like fiddle leaf figs or calatheas")

    # Weather-specific tips if available
    weather_tips = []
    if weather:
        weather_tips = seasonal_context.get_weather_proactive_advice(weather, forecast)

    return {
        "user_preferences": preferences,
        "has_preferences": bool(preferences),
        "seasonal": {
            "season": season_ctx["season"],
            "timing": season_ctx["timing"],
            "context_summary": season_ctx["context_summary"],
            "seasonal_tips": season_ctx["seasonal_tips"],
            "timely_focus": timely_focus
        },
        "weather": {
            "current": weather,
            "tips": weather_tips
        } if weather else None,
        "personalized_guidance": guidance,
        "stats": {
            "total_plants": 0,
            "active_reminders": 0
        }
    }
