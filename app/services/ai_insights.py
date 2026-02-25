"""
AI Insights Service - Pattern recognition for personalized care advice.

Analyzes user's plant care history to identify patterns, health trends,
and provide context-aware insights for AI responses.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from collections import defaultdict


def extract_health_keywords(text: str) -> List[str]:
    """
    Extract health-related keywords from notes/observations.

    Args:
        text: User's note or observation text

    Returns:
        List of standardized keywords:
        - Negative: yellow_leaves, brown_tips, droopy, wilting, pest_spotted, etc.
        - Positive: new_growth, thriving, flowering, healthy, etc.

    Example:
        >>> extract_health_keywords("Leaves are yellowing at the tips")
        ['yellow_leaves', 'brown_tips']
    """
    if not text:
        return []

    text_lower = text.lower()
    keywords = []

    # Negative indicators
    if any(word in text_lower for word in ["yellow", "yellowing"]):
        keywords.append("yellow_leaves")
    if any(word in text_lower for word in ["brown", "browning"]):
        keywords.append("brown_tips")
    if "droopy" in text_lower or "drooping" in text_lower:
        keywords.append("droopy")
    if "wilting" in text_lower or "wilt" in text_lower:
        keywords.append("wilting")
    if any(word in text_lower for word in ["pest", "bug", "insect", "spider", "aphid"]):
        keywords.append("pest_spotted")
    if any(word in text_lower for word in ["dry", "dried", "crispy", "crisp"]):
        keywords.append("dry_soil")
    if any(word in text_lower for word in ["overwater", "soggy", "wet", "root rot"]):
        keywords.append("overwatered")

    # Positive indicators
    if any(word in text_lower for word in ["new leaf", "new growth", "growing", "sprouting"]):
        keywords.append("new_growth")
    if any(word in text_lower for word in ["thriving", "healthy", "doing well", "great", "perfect"]):
        keywords.append("thriving")
    if any(word in text_lower for word in ["flower", "flowering", "bloom", "blooming", "bud"]):
        keywords.append("flowering")

    return keywords


def calculate_watering_pattern(activities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate watering pattern from activity history.

    Args:
        activities: List of plant action dicts with action_type and action_at

    Returns:
        {
            "avg_interval_days": float or None,
            "consistency": "regular" | "irregular" | "insufficient_data",
            "recent_trend": "increasing_frequency" | "decreasing_frequency" | "stable" | "insufficient_data",
            "sample_size": int
        }

    Example:
        >>> activities = [
        ...     {"action_type": "water", "action_at": "2024-01-01T10:00:00Z"},
        ...     {"action_type": "water", "action_at": "2024-01-05T10:00:00Z"},
        ...     {"action_type": "water", "action_at": "2024-01-09T10:00:00Z"},
        ... ]
        >>> pattern = calculate_watering_pattern(activities)
        >>> pattern["avg_interval_days"]
        4.0
        >>> pattern["consistency"]
        'regular'
    """
    # Filter to only watering actions
    water_actions = [
        a for a in activities
        if a.get("action_type") == "water"
    ]

    if len(water_actions) < 2:
        return {
            "avg_interval_days": None,
            "consistency": "insufficient_data",
            "recent_trend": "insufficient_data",
            "sample_size": 0
        }

    # Sort by date (oldest to newest)
    water_actions.sort(key=lambda x: x.get("action_at", ""))

    # Calculate intervals between consecutive waterings
    intervals = []
    for i in range(1, len(water_actions)):
        prev_date_str = water_actions[i-1].get("action_at", "")
        curr_date_str = water_actions[i].get("action_at", "")

        if not prev_date_str or not curr_date_str:
            continue

        try:
            prev_date = datetime.fromisoformat(prev_date_str.replace('Z', '+00:00'))
            curr_date = datetime.fromisoformat(curr_date_str.replace('Z', '+00:00'))
            interval = (curr_date - prev_date).days
            if interval > 0:  # Only positive intervals
                intervals.append(interval)
        except (ValueError, AttributeError):
            continue

    if not intervals:
        return {
            "avg_interval_days": None,
            "consistency": "insufficient_data",
            "recent_trend": "insufficient_data",
            "sample_size": 0
        }

    # Calculate average interval
    avg_interval = sum(intervals) / len(intervals)

    # Calculate standard deviation for consistency
    variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
    std_dev = variance ** 0.5

    # Determine consistency (regular if std dev < 30% of average)
    consistency = "regular" if std_dev < avg_interval * 0.3 else "irregular"

    # Detect trends (compare recent half to older half)
    recent_trend = "insufficient_data"
    if len(intervals) >= 4:
        mid = len(intervals) // 2
        recent_avg = sum(intervals[mid:]) / len(intervals[mid:])
        older_avg = sum(intervals[:mid]) / len(intervals[:mid])

        if recent_avg > older_avg * 1.2:
            recent_trend = "decreasing_frequency"  # Longer intervals = less frequent watering
        elif recent_avg < older_avg * 0.8:
            recent_trend = "increasing_frequency"  # Shorter intervals = more frequent watering
        else:
            recent_trend = "stable"

    return {
        "avg_interval_days": round(avg_interval, 1),
        "consistency": consistency,
        "recent_trend": recent_trend,
        "sample_size": len(intervals)
    }


def identify_health_trends(activities_with_notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Identify health trends from journal observations.

    Args:
        activities_with_notes: List of activities with 'notes' and 'days_ago' fields

    Returns:
        {
            "recent_concerns": List[str],  # Keywords from last 7 days
            "improving": bool,              # Fewer issues recently vs before
            "deteriorating": bool,          # More issues recently vs before
            "timeline": List[Dict],         # Recent observations with concerns
            "total_observations": int
        }

    Example:
        >>> activities = [
        ...     {"days_ago": 2, "notes": "Looking healthy now"},
        ...     {"days_ago": 10, "notes": "Leaves were yellowing"},
        ... ]
        >>> trends = identify_health_trends(activities)
        >>> trends["improving"]
        True
    """
    # Extract keywords from all notes
    timeline = []
    for activity in activities_with_notes:
        note_text = activity.get("notes")
        if note_text:
            keywords = extract_health_keywords(note_text)
            if keywords:
                timeline.append({
                    "days_ago": activity.get("days_ago", 0),
                    "concerns": keywords,
                    "note_preview": note_text[:50]
                })

    # Sort by recency (most recent first)
    timeline.sort(key=lambda x: x["days_ago"])

    # Identify current concerns (last 7 days)
    recent_concerns = set()
    for entry in timeline:
        if entry["days_ago"] <= 7:
            recent_concerns.update(entry["concerns"])

    # Define negative keywords for trend detection
    negative_keywords = [
        "yellow_leaves", "brown_tips", "droopy",
        "wilting", "pest_spotted", "dry_soil", "overwatered"
    ]

    # Detect improving/deteriorating trends
    improving = False
    deteriorating = False

    if len(timeline) >= 2:
        # Compare recent (last 7d) to older (7-14d) observations
        recent_negative = sum(
            1 for e in timeline
            if e["days_ago"] <= 7 and any(
                c in negative_keywords for c in e["concerns"]
            )
        )
        older_negative = sum(
            1 for e in timeline
            if 7 < e["days_ago"] <= 14 and any(
                c in negative_keywords for c in e["concerns"]
            )
        )

        # Improving: had issues before, fewer/none now
        if older_negative > 0 and recent_negative < older_negative:
            improving = True
        # Deteriorating: more issues now than before
        elif recent_negative > older_negative and recent_negative > 0:
            deteriorating = True

    return {
        "recent_concerns": list(recent_concerns),
        "improving": improving,
        "deteriorating": deteriorating,
        "timeline": timeline[:5],  # Most recent 5 entries with concerns
        "total_observations": len(timeline)
    }


def extract_weather_context_summary(weather: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Extract concise weather context for AI prompts.

    Identifies relevant weather conditions that affect plant care:
    - Heat stress conditions
    - Cold/freeze risk
    - High humidity (mold/fungus risk)
    - Low humidity (dry air)
    - Wind conditions
    - Rain/watering implications

    Args:
        weather: Weather dict from weather service

    Returns:
        Concise weather summary string or None if no weather data

    Example:
        >>> weather = {"temp_f": 95, "humidity": 25, "wind_mph": 20, "conditions": "clear"}
        >>> extract_weather_context_summary(weather)
        'Hot & dry (95°F, 25% humidity), windy (20mph) - increased water needs'
    """
    if not weather:
        return None

    temp_f = weather.get("temp_f", 70)
    humidity = weather.get("humidity", 50)
    wind_mph = weather.get("wind_mph", 0)
    conditions = (weather.get("conditions") or "").lower()

    context_parts = []
    care_implications = []

    # Temperature context
    if temp_f >= 95:
        context_parts.append(f"very hot ({temp_f}°F)")
        care_implications.append("heat stress risk")
    elif temp_f >= 85:
        context_parts.append(f"hot ({temp_f}°F)")
        care_implications.append("increased water needs")
    elif temp_f <= 35:
        context_parts.append(f"freezing risk ({temp_f}°F)")
        care_implications.append("protect outdoor plants")
    elif temp_f <= 50:
        context_parts.append(f"cold ({temp_f}°F)")
        care_implications.append("reduce watering")

    # Humidity context
    if humidity < 20:
        context_parts.append(f"very dry air ({humidity}%)")
        care_implications.append("consider misting")
    elif humidity < 30:
        context_parts.append(f"dry air ({humidity}%)")
    elif humidity > 80:
        context_parts.append(f"humid ({humidity}%)")
        care_implications.append("fungal risk, ensure airflow")

    # Wind context (relevant for outdoor plants)
    if wind_mph >= 25:
        context_parts.append(f"very windy ({wind_mph}mph)")
        care_implications.append("secure outdoor plants")
    elif wind_mph >= 15:
        context_parts.append(f"windy ({wind_mph}mph)")

    # Rain/precipitation context
    if any(word in conditions for word in ["rain", "shower", "storm", "drizzle"]):
        context_parts.append("rain expected")
        care_implications.append("delay outdoor watering")

    # Build final summary
    if not context_parts:
        return None

    summary = ", ".join(context_parts)
    if care_implications:
        summary += f" - {', '.join(care_implications)}"

    return summary


def analyze_care_completeness(
    plant_id: str,
    activities: List[Dict[str, Any]],
    reminders: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Analyze how well a plant is being cared for based on activity vs reminder schedule.

    Args:
        plant_id: Plant UUID
        activities: Recent activities for this plant
        reminders: Active reminders for this plant

    Returns:
        {
            "completion_rate": float (0.0-1.0) or None,
            "on_schedule": bool,
            "care_level": "excellent" | "good" | "needs_attention" | "unknown",
            "missed_care_types": List[str]
        }

    Example:
        Helps AI say: "You've been caring for this plant consistently - great job!"
        or "This plant hasn't been watered in 10 days - check soil moisture"
    """
    if not activities and not reminders:
        return {
            "completion_rate": None,
            "on_schedule": True,
            "care_level": "unknown",
            "missed_care_types": []
        }

    # Count activities by type in last 30 days
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    recent_activity_types = set()

    for activity in activities:
        action_at = activity.get("action_at")
        if action_at:
            try:
                if isinstance(action_at, str):
                    action_at = datetime.fromisoformat(action_at.replace('Z', '+00:00'))

                if action_at >= thirty_days_ago:
                    action_type = activity.get("action_type")
                    if action_type:
                        recent_activity_types.add(action_type)
            except (ValueError, AttributeError):
                continue

    # Check which reminder types are active but haven't been done
    active_reminder_types = set(r.get("reminder_type") for r in reminders if r.get("is_active"))
    missed_care_types = []

    # Map reminder types to action types
    reminder_to_action = {
        "watering": "water",
        "fertilizing": "fertilize",
        "misting": "mist",
        "pruning": "prune",
        "repotting": "repot"
    }

    for reminder_type in active_reminder_types:
        action_type = reminder_to_action.get(reminder_type, reminder_type)
        if action_type not in recent_activity_types:
            missed_care_types.append(reminder_type)

    # Calculate care level
    if len(active_reminder_types) == 0:
        care_level = "unknown"
        on_schedule = True
        completion_rate = None
    else:
        completion_rate = len(recent_activity_types) / len(active_reminder_types)

        if completion_rate >= 0.9:
            care_level = "excellent"
            on_schedule = True
        elif completion_rate >= 0.7:
            care_level = "good"
            on_schedule = True
        else:
            care_level = "needs_attention"
            on_schedule = False

    return {
        "completion_rate": completion_rate,
        "on_schedule": on_schedule,
        "care_level": care_level,
        "missed_care_types": missed_care_types
    }


def summarize_recent_observations(
    activities: List[Dict[str, Any]],
    max_observations: int = 3
) -> List[Dict[str, Any]]:
    """
    Extract most relevant recent observations with health keywords.

    Prioritizes:
    1. Recent observations with health concerns (last 7 days)
    2. Recent positive observations
    3. Most recent observations overall

    Args:
        activities: Activities with notes and days_ago
        max_observations: Maximum number to return (default 3)

    Returns:
        List of dicts with days_ago, note_preview, and keywords
    """
    observations = []

    for activity in activities:
        note = activity.get("notes")
        if note and note.strip():
            keywords = extract_health_keywords(note)
            observations.append({
                "days_ago": activity.get("days_ago", 0),
                "action_type": activity.get("action_type"),
                "note_preview": note[:100],  # Truncate to 100 chars
                "keywords": keywords,
                "has_concern": any(
                    kw in ["yellow_leaves", "brown_tips", "droopy", "wilting", "pest_spotted", "overwatered"]
                    for kw in keywords
                )
            })

    # Sort by priority:
    # 1. Recent concerns (last 7 days with negative keywords)
    # 2. Recent observations (last 7 days)
    # 3. Any observations
    def priority_score(obs):
        days = obs["days_ago"]
        has_concern = obs["has_concern"]

        if has_concern and days <= 7:
            return 1000 - days  # Highest priority
        elif days <= 7:
            return 500 - days   # Medium priority
        else:
            return 100 - days   # Lower priority

    observations.sort(key=priority_score, reverse=True)

    return observations[:max_observations]
