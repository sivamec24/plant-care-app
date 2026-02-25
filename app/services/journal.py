"""
Journal/Activity service for plant care tracking.

Handles creating and retrieving plant care activities (watering, fertilizing,
notes, photos, etc.) using the plant_actions table.
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
import logging
from flask import current_app, has_app_context
from app.services.supabase_client import get_admin_client

logger = logging.getLogger(__name__)


def _safe_log_error(message: str) -> None:
    """Safely log an error, handling cases where no app context exists."""
    if has_app_context():
        current_app.logger.error(message)
    else:
        logger.error(message)


# Action type display names
ACTION_TYPE_NAMES = {
    'water': 'Watering',
    'fertilize': 'Fertilizing',
    'repot': 'Repotting',
    'prune': 'Pruning',
    'note': 'Note',
    'pest': 'Pest Treatment',
}

# Action type emojis
ACTION_TYPE_EMOJIS = {
    'water': '💧',
    'fertilize': '🌿',
    'repot': '🪴',
    'prune': '✂️',
    'note': '📝',
    'pest': '🐛',
}


def create_plant_action(
    user_id: str,
    plant_id: str,
    action_type: str,
    notes: Optional[str] = None,
    amount_ml: Optional[int] = None,
    photo_url: Optional[str] = None,
    photo_url_thumb: Optional[str] = None,
    action_at: Optional[datetime] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Create a new plant care action/journal entry.

    Args:
        user_id: User's UUID
        plant_id: Plant's UUID
        action_type: Type of action (water, fertilize, repot, prune, note, pest)
        notes: Optional notes about the action
        amount_ml: Optional amount in milliliters (for watering/fertilizing)
        photo_url: Optional photo URL (display version)
        photo_url_thumb: Optional thumbnail photo URL (128x128)
        action_at: Optional timestamp (defaults to now)

    Returns:
        (action_dict, error_message)
    """
    supabase = get_admin_client()
    if not supabase:
        return None, "Database not configured"

    # Validate action type
    valid_actions = ['water', 'fertilize', 'repot', 'prune', 'note', 'pest']
    if action_type not in valid_actions:
        return None, f"Invalid action type. Must be one of: {', '.join(valid_actions)}"

    try:
        # Prepare action data
        action_data = {
            "user_id": user_id,
            "plant_id": plant_id,
            "action_type": action_type,
            "notes": notes,
            "amount_ml": amount_ml,
            "photo_url": photo_url,
            "photo_url_thumb": photo_url_thumb,
        }

        if action_at:
            action_data["action_at"] = action_at.isoformat()

        # Insert action
        response = supabase.table("plant_actions").insert(action_data).execute()

        if response.data:
            return response.data[0], None
        return None, "Failed to create action"

    except Exception as e:
        return None, f"Error creating action: {str(e)}"


def get_user_actions(
    user_id: str,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Get all actions for all of a user's plants in a single query.

    This is more efficient than calling get_plant_actions() for each plant
    when you need activities across multiple plants (avoids N+1 queries).

    Args:
        user_id: User's UUID
        limit: Maximum number of actions to return
        offset: Number of actions to skip

    Returns:
        List of action dictionaries with plant_name joined, sorted by most recent first
    """
    supabase = get_admin_client()
    if not supabase:
        return []

    try:
        # Single query to get all user's activities with plant names joined
        response = supabase.table("plant_actions") \
            .select("*, plants!inner(name)") \
            .eq("user_id", user_id) \
            .order("action_at", desc=True) \
            .limit(limit) \
            .range(offset, offset + limit - 1) \
            .execute()

        if response.data:
            # Flatten the nested plant data
            activities = []
            for action in response.data:
                # Extract plant name from joined data
                plant_data = action.pop("plants", {})
                action["plant_name"] = plant_data.get("name", "Unknown")
                activities.append(action)
            return activities
        return []

    except Exception as e:
        _safe_log_error(f"Error fetching user actions: {str(e)}")
        return []


def get_plant_actions(
    plant_id: str,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Get all actions for a specific plant.

    Args:
        plant_id: Plant's UUID
        user_id: User's UUID (for authorization)
        limit: Maximum number of actions to return
        offset: Number of actions to skip

    Returns:
        List of action dictionaries, sorted by most recent first
    """
    supabase = get_admin_client()
    if not supabase:
        return []

    try:
        response = supabase.table("plant_actions") \
            .select("*") \
            .eq("plant_id", plant_id) \
            .eq("user_id", user_id) \
            .order("action_at", desc=True) \
            .limit(limit) \
            .offset(offset) \
            .execute()

        return response.data if response.data else []

    except Exception as e:
        _safe_log_error(f"Error fetching plant actions: {e}")
        return []


def get_plant_actions_batch(
    plant_ids: List[str],
    user_id: str,
    limit_per_plant: int = 50,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get actions for multiple plants in a single query (avoids N+1 queries).

    Args:
        plant_ids: List of plant UUIDs
        user_id: User's UUID (for authorization)
        limit_per_plant: Maximum actions per plant (applied after fetch)

    Returns:
        Dict mapping plant_id -> list of actions
    """
    if not plant_ids:
        return {}

    supabase = get_admin_client()
    if not supabase:
        return {}

    try:
        # Fetch all actions for the given plants in one query
        response = supabase.table("plant_actions") \
            .select("*") \
            .in_("plant_id", plant_ids) \
            .eq("user_id", user_id) \
            .order("action_at", desc=True) \
            .execute()

        # Group by plant_id and limit per plant
        result: Dict[str, List[Dict[str, Any]]] = {pid: [] for pid in plant_ids}
        if response.data:
            for action in response.data:
                pid = action.get("plant_id")
                if pid in result and len(result[pid]) < limit_per_plant:
                    result[pid].append(action)

        return result

    except Exception as e:
        _safe_log_error(f"Error fetching batch plant actions: {e}")
        return {}


def get_last_watered_date(
    plant_id: str,
    user_id: str,
) -> Optional[datetime]:
    """
    Get the datetime of the last watering for a specific plant.

    Args:
        plant_id: Plant's UUID
        user_id: User's UUID (for authorization)

    Returns:
        datetime of last watering, or None if never watered
    """
    supabase = get_admin_client()
    if not supabase:
        return None

    try:
        response = supabase.table("plant_actions") \
            .select("action_at") \
            .eq("plant_id", plant_id) \
            .eq("user_id", user_id) \
            .eq("action_type", "water") \
            .order("action_at", desc=True) \
            .limit(1) \
            .execute()

        if response.data and len(response.data) > 0:
            action_at = response.data[0].get("action_at")
            if action_at:
                # Parse ISO format datetime string
                if isinstance(action_at, str):
                    return datetime.fromisoformat(action_at.replace('Z', '+00:00'))
                return action_at
        return None

    except Exception as e:
        _safe_log_error(f"Error fetching last watered date: {e}")
        return None


def get_recent_actions(
    user_id: str,
    days: int = 7,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Get recent actions across all user's plants.

    Args:
        user_id: User's UUID
        days: Number of days to look back
        limit: Maximum number of actions to return

    Returns:
        List of action dictionaries with plant info, sorted by most recent first
    """
    supabase = get_admin_client()
    if not supabase:
        return []

    try:
        from datetime import timedelta
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        response = supabase.table("plant_actions") \
            .select("*, plants(id, name, nickname, photo_url)") \
            .eq("user_id", user_id) \
            .gte("action_at", cutoff_date.isoformat()) \
            .order("action_at", desc=True) \
            .limit(limit) \
            .execute()

        return response.data if response.data else []

    except Exception as e:
        _safe_log_error(f"Error fetching recent actions: {e}")
        return []


def get_action_by_id(
    action_id: str,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Get a single action by ID (with ownership check).

    Args:
        action_id: Action's UUID
        user_id: User's UUID (for authorization)

    Returns:
        Action dictionary or None
    """
    supabase = get_admin_client()
    if not supabase:
        return None

    try:
        response = supabase.table("plant_actions") \
            .select("*, plants(id, name, nickname, photo_url)") \
            .eq("id", action_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        return response.data if response.data else None

    except Exception as e:
        _safe_log_error(f"Error fetching action: {e}")
        return None


def update_action(
    action_id: str,
    user_id: str,
    **kwargs
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Update a plant action's fields.

    Args:
        action_id: Action's UUID
        user_id: User's UUID (for authorization)
        **kwargs: Fields to update (notes, amount_ml, photo_url)

    Returns:
        (updated_action, error_message)
    """
    supabase = get_admin_client()
    if not supabase:
        return None, "Database not configured"

    # Remove fields that shouldn't be updated
    disallowed_fields = ['id', 'user_id', 'plant_id', 'action_type', 'action_at']
    update_data = {k: v for k, v in kwargs.items() if k not in disallowed_fields}

    if not update_data:
        return None, "No fields to update"

    try:
        response = supabase.table("plant_actions").update(update_data).eq(
            "id", action_id
        ).eq("user_id", user_id).execute()

        if response.data:
            return response.data[0], None
        return None, "Failed to update action"

    except Exception as e:
        return None, f"Error updating action: {str(e)}"


def delete_action(
    action_id: str,
    user_id: str,
) -> Tuple[bool, Optional[str]]:
    """
    Delete a plant action.

    Args:
        action_id: Action's UUID
        user_id: User's UUID (for authorization)

    Returns:
        (success, error_message)
    """
    supabase = get_admin_client()
    if not supabase:
        return False, "Database not configured"

    try:
        response = supabase.table("plant_actions").delete().eq(
            "id", action_id
        ).eq("user_id", user_id).execute()

        if response.data:
            return True, None
        return False, "Action not found or unauthorized"

    except Exception as e:
        return False, f"Error deleting action: {str(e)}"


def get_action_stats(plant_id: str, user_id: str) -> Dict[str, Any]:
    """
    Get statistics about actions for a plant.

    Args:
        plant_id: Plant's UUID
        user_id: User's UUID

    Returns:
        Dictionary with action counts and last action dates
    """
    supabase = get_admin_client()
    if not supabase:
        return {
            "total_actions": 0,
            "watering_count": 0,
            "fertilizing_count": 0,
            "last_watered": None,
            "last_fertilized": None,
        }

    try:
        # Get all actions for this plant
        actions = get_plant_actions(plant_id, user_id, limit=1000)

        stats = {
            "total_actions": len(actions),
            "watering_count": 0,
            "fertilizing_count": 0,
            "repotting_count": 0,
            "pruning_count": 0,
            "note_count": 0,
            "pest_count": 0,
            "last_watered": None,
            "last_fertilized": None,
            "last_action": None,
        }

        for action in actions:
            action_type = action.get("action_type")
            action_at = action.get("action_at")

            # Count by type
            if action_type == "water":
                stats["watering_count"] += 1
                if not stats["last_watered"]:
                    stats["last_watered"] = action_at
            elif action_type == "fertilize":
                stats["fertilizing_count"] += 1
                if not stats["last_fertilized"]:
                    stats["last_fertilized"] = action_at
            elif action_type == "repot":
                stats["repotting_count"] += 1
            elif action_type == "prune":
                stats["pruning_count"] += 1
            elif action_type == "note":
                stats["note_count"] += 1
            elif action_type == "pest":
                stats["pest_count"] += 1

            # Track last action overall
            if not stats["last_action"]:
                stats["last_action"] = action_at

        return stats

    except Exception as e:
        _safe_log_error(f"Error calculating action stats: {e}")
        return {
            "total_actions": 0,
            "watering_count": 0,
            "fertilizing_count": 0,
            "last_watered": None,
            "last_fertilized": None,
        }


def append_note_to_recent_action(
    plant_id: str,
    user_id: str,
    note_text: str,
    max_age_minutes: int = 5
) -> Tuple[bool, Optional[str]]:
    """
    Append a note to the most recent journal action for a plant.

    Used to add weather adjustment notes when completing reminders (Phase 2C).

    Args:
        plant_id: Plant's UUID
        user_id: User's UUID (for authorization)
        note_text: Text to append to the existing notes
        max_age_minutes: Maximum age of action to update (default 5 minutes)

    Returns:
        (success, error_message)
    """
    from datetime import datetime, timedelta, timezone
    from .supabase_client import get_admin_client

    supabase = get_admin_client()
    if not supabase:
        return False, "Database not configured"

    try:
        # Find most recent action for this plant within the time window
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

        response = supabase.table("plant_actions").select("id, notes").eq(
            "plant_id", plant_id
        ).eq(
            "user_id", user_id
        ).gte(
            "action_at", cutoff_time.isoformat()
        ).order(
            "action_at", desc=True
        ).limit(1).execute()

        if not response.data or len(response.data) == 0:
            # No recent action found - this is not an error, just skip
            return True, None

        action = response.data[0]
        action_id = action["id"]
        existing_notes = action.get("notes") or ""

        # Append new note to existing notes
        updated_notes = existing_notes + note_text

        # Update the action
        update_response = supabase.table("plant_actions").update({
            "notes": updated_notes
        }).eq("id", action_id).eq("user_id", user_id).execute()

        if update_response.data:
            return True, None
        else:
            return False, "Failed to update action notes"

    except Exception as e:
        _safe_log_error(f"Error appending note to recent action: {e}")
        return False, str(e)
