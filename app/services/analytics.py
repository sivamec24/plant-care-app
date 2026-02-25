"""
Analytics event tracking service.

Tracks user behavior events for product metrics:
- Activation Rate (users who add first plant)
- Weekly Active Users (WAU)
- Monthly Active Users (MAU)
- Reminder Completion Rate
- Stickiness (WAU/MAU)
- D30 Retention
"""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime, date, timedelta
import logging
from app.services.supabase_client import get_admin_client

logger = logging.getLogger(__name__)


# Event type constants
EVENT_USER_SIGNUP = "user_signup"
EVENT_USER_FIRST_LOGIN = "user_first_login"
EVENT_PLANT_ADDED = "plant_added"
EVENT_FIRST_PLANT_ADDED = "first_plant_added"
EVENT_REMINDER_CREATED = "reminder_created"
EVENT_REMINDER_COMPLETED = "reminder_completed"
EVENT_REMINDER_SNOOZED = "reminder_snoozed"
EVENT_JOURNAL_ENTRY_CREATED = "journal_entry_created"
EVENT_AI_QUESTION_ASKED = "ai_question_asked"
EVENT_PAGE_VIEW = "page_view"


def track_event(
    user_id: str,
    event_type: str,
    event_data: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Track an analytics event.

    Args:
        user_id: UUID of the user performing the action
        event_type: Type of event (use EVENT_* constants)
        event_data: Optional JSON data associated with the event

    Returns:
        Tuple of (event_id, error_message)
    """
    if event_data is None:
        event_data = {}

    try:
        supabase = get_admin_client()

        # Call database function to track event
        result = supabase.rpc(
            "track_analytics_event",
            {
                "p_user_id": user_id,
                "p_event_type": event_type,
                "p_event_data": event_data,
            },
        ).execute()

        if result.data:
            return result.data, None
        else:
            return None, "Failed to track event"

    except Exception as e:
        logger.error(f"Error tracking analytics event: {str(e)}", exc_info=True)
        return None, "Failed to track event"


def get_activation_rate(
    start_date: Optional[date] = None, end_date: Optional[date] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Get activation rate (% of users who added at least one plant).

    Args:
        start_date: Start date for cohort (default: 30 days ago)
        end_date: End date for cohort (default: today)

    Returns:
        Tuple of (stats_dict, error_message)
        stats_dict contains: total_signups, activated_users, activation_rate
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=30)
    if end_date is None:
        end_date = date.today()

    try:
        supabase = get_admin_client()

        result = supabase.rpc(
            "get_activation_rate",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
            },
        ).execute()

        if result.data and len(result.data) > 0:
            return result.data[0], None
        else:
            return None, "No data available"

    except Exception as e:
        logger.error(f"Error getting activation rate: {str(e)}", exc_info=True)
        return None, "Failed to get activation rate"


def get_weekly_active_users(end_date: Optional[date] = None) -> Tuple[Optional[int], Optional[str]]:
    """
    Get Weekly Active Users (WAU).

    Args:
        end_date: End date for the week (default: today)

    Returns:
        Tuple of (wau_count, error_message)
    """
    if end_date is None:
        end_date = date.today()

    try:
        supabase = get_admin_client()

        result = supabase.rpc(
            "get_weekly_active_users", {"p_end_date": end_date.isoformat()}
        ).execute()

        if result.data is not None:
            return result.data, None
        else:
            return None, "No data available"

    except Exception as e:
        logger.error(f"Error getting WAU: {str(e)}", exc_info=True)
        return None, "Failed to get WAU"


def get_monthly_active_users(end_date: Optional[date] = None) -> Tuple[Optional[int], Optional[str]]:
    """
    Get Monthly Active Users (MAU).

    Args:
        end_date: End date for the month (default: today)

    Returns:
        Tuple of (mau_count, error_message)
    """
    if end_date is None:
        end_date = date.today()

    try:
        supabase = get_admin_client()

        result = supabase.rpc(
            "get_monthly_active_users", {"p_end_date": end_date.isoformat()}
        ).execute()

        if result.data is not None:
            return result.data, None
        else:
            return None, "No data available"

    except Exception as e:
        logger.error(f"Error getting MAU: {str(e)}", exc_info=True)
        return None, "Failed to get MAU"


def get_stickiness(end_date: Optional[date] = None) -> Tuple[Optional[float], Optional[str]]:
    """
    Get stickiness ratio (WAU/MAU * 100).

    Args:
        end_date: End date for calculation (default: today)

    Returns:
        Tuple of (stickiness_percentage, error_message)
    """
    if end_date is None:
        end_date = date.today()

    try:
        supabase = get_admin_client()

        result = supabase.rpc("get_stickiness", {"p_end_date": end_date.isoformat()}).execute()

        if result.data is not None:
            return result.data, None
        else:
            return None, "No data available"

    except Exception as e:
        logger.error(f"Error getting stickiness: {str(e)}", exc_info=True)
        return None, "Failed to get stickiness"


def get_reminder_completion_rate(
    start_date: Optional[date] = None, end_date: Optional[date] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Get reminder completion rate.

    Args:
        start_date: Start date for period (default: 30 days ago)
        end_date: End date for period (default: today)

    Returns:
        Tuple of (stats_dict, error_message)
        stats_dict contains: total_completions, total_due, completion_rate
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=30)
    if end_date is None:
        end_date = date.today()

    try:
        supabase = get_admin_client()

        result = supabase.rpc(
            "get_reminder_completion_rate",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
            },
        ).execute()

        if result.data and len(result.data) > 0:
            return result.data[0], None
        else:
            return None, "No data available"

    except Exception as e:
        logger.error(f"Error getting reminder completion rate: {str(e)}", exc_info=True)
        return None, "Failed to get reminder completion rate"


def get_d30_retention(
    cohort_start_date: Optional[date] = None, cohort_end_date: Optional[date] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Get D30 retention rate (% of users active 30 days after signup).

    Args:
        cohort_start_date: Start date for signup cohort (default: 60 days ago)
        cohort_end_date: End date for signup cohort (default: 30 days ago)

    Returns:
        Tuple of (stats_dict, error_message)
        stats_dict contains: cohort_size, retained_users, retention_rate
    """
    if cohort_start_date is None:
        cohort_start_date = date.today() - timedelta(days=60)
    if cohort_end_date is None:
        cohort_end_date = date.today() - timedelta(days=30)

    try:
        supabase = get_admin_client()

        result = supabase.rpc(
            "get_d30_retention",
            {
                "p_cohort_start_date": cohort_start_date.isoformat(),
                "p_cohort_end_date": cohort_end_date.isoformat(),
            },
        ).execute()

        if result.data and len(result.data) > 0:
            return result.data[0], None
        else:
            return None, "No data available"

    except Exception as e:
        logger.error(f"Error getting D30 retention: {str(e)}", exc_info=True)
        return None, "Failed to get D30 retention"


def get_all_metrics() -> Dict[str, Any]:
    """
    Get all key product metrics in one call.

    Returns:
        Dictionary containing all metrics with error handling
    """
    metrics = {
        "activation": None,
        "wau": None,
        "mau": None,
        "stickiness": None,
        "reminder_completion": None,
        "d30_retention": None,
        "errors": [],
    }

    # Activation rate (last 30 days)
    activation, error = get_activation_rate()
    if error:
        metrics["errors"].append(f"Activation: {error}")
    else:
        metrics["activation"] = activation

    # WAU
    wau, error = get_weekly_active_users()
    if error:
        metrics["errors"].append(f"WAU: {error}")
    else:
        metrics["wau"] = wau

    # MAU
    mau, error = get_monthly_active_users()
    if error:
        metrics["errors"].append(f"MAU: {error}")
    else:
        metrics["mau"] = mau

    # Stickiness
    stickiness, error = get_stickiness()
    if error:
        metrics["errors"].append(f"Stickiness: {error}")
    else:
        metrics["stickiness"] = stickiness

    # Reminder completion rate (last 30 days)
    completion, error = get_reminder_completion_rate()
    if error:
        metrics["errors"].append(f"Reminder completion: {error}")
    else:
        metrics["reminder_completion"] = completion

    # D30 retention
    retention, error = get_d30_retention()
    if error:
        metrics["errors"].append(f"D30 retention: {error}")
    else:
        metrics["d30_retention"] = retention

    return metrics


def get_total_counts() -> Dict[str, Any]:
    """
    Get total counts for users, plants, reminders, and journal entries.

    Returns:
        Dictionary with counts and any errors
    """
    counts = {
        "users": 0,
        "plants": 0,
        "reminders": 0,
        "journal_entries": 0,
        "errors": [],
    }

    try:
        supabase = get_admin_client()

        # Count users
        result = supabase.table("profiles").select("id", count="exact").execute()
        counts["users"] = result.count or 0

        # Count plants
        result = supabase.table("plants").select("id", count="exact").execute()
        counts["plants"] = result.count or 0

        # Count reminders
        result = supabase.table("reminders").select("id", count="exact").execute()
        counts["reminders"] = result.count or 0

        # Count journal entries (plant_actions)
        result = supabase.table("plant_actions").select("id", count="exact").execute()
        counts["journal_entries"] = result.count or 0

    except Exception as e:
        logger.error(f"Error getting total counts: {str(e)}", exc_info=True)
        counts["errors"].append(f"Failed to get counts: {str(e)}")

    return counts


def get_signups_by_week(weeks: int = 12) -> Tuple[Optional[list], Optional[str]]:
    """
    Get signup counts grouped by week.

    Args:
        weeks: Number of weeks to look back (default: 12)

    Returns:
        Tuple of (list of {week_start, count}, error_message)
    """
    try:
        supabase = get_admin_client()
        end_date = date.today()
        start_date = end_date - timedelta(weeks=weeks)

        # Query profiles created in the date range
        result = (
            supabase.table("profiles")
            .select("created_at")
            .gte("created_at", start_date.isoformat())
            .lte("created_at", end_date.isoformat())
            .execute()
        )

        if not result.data:
            return [], None

        # Group by week
        from collections import defaultdict
        weekly_counts = defaultdict(int)

        for profile in result.data:
            created = datetime.fromisoformat(profile["created_at"].replace("Z", "+00:00"))
            # Get the Monday of that week
            week_start = created.date() - timedelta(days=created.weekday())
            weekly_counts[week_start.isoformat()] += 1

        # Convert to sorted list
        weeks_list = [
            {"week_start": week, "count": count}
            for week, count in sorted(weekly_counts.items())
        ]

        return weeks_list, None

    except Exception as e:
        logger.error(f"Error getting signups by week: {str(e)}", exc_info=True)
        return None, f"Failed to get signup data: {str(e)}"


def get_event_counts_by_type(
    start_date: Optional[date] = None, end_date: Optional[date] = None
) -> Tuple[Optional[Dict[str, int]], Optional[str]]:
    """
    Get counts of analytics events grouped by type.

    Args:
        start_date: Start date (default: 30 days ago)
        end_date: End date (default: today)

    Returns:
        Tuple of ({event_type: count}, error_message)
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=30)
    if end_date is None:
        end_date = date.today()

    try:
        supabase = get_admin_client()

        result = (
            supabase.table("analytics_events")
            .select("event_type")
            .gte("created_at", start_date.isoformat())
            .lte("created_at", (end_date + timedelta(days=1)).isoformat())
            .execute()
        )

        if not result.data:
            return {}, None

        # Count by type
        from collections import Counter
        type_counts = Counter(event["event_type"] for event in result.data)

        return dict(type_counts), None

    except Exception as e:
        logger.error(f"Error getting event counts: {str(e)}", exc_info=True)
        return None, f"Failed to get event data: {str(e)}"


def get_recent_events(limit: int = 20) -> Tuple[Optional[list], Optional[str]]:
    """
    Get recent analytics events for activity feed.

    Args:
        limit: Maximum number of events to return

    Returns:
        Tuple of (list of events, error_message)
    """
    try:
        supabase = get_admin_client()

        result = (
            supabase.table("analytics_events")
            .select("id, user_id, event_type, event_data, created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        return result.data or [], None

    except Exception as e:
        logger.error(f"Error getting recent events: {str(e)}", exc_info=True)
        return None, f"Failed to get recent events: {str(e)}"


def get_users_list(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None
) -> Tuple[Optional[list], int, Optional[str]]:
    """
    Get paginated list of users with basic stats.

    Args:
        limit: Number of users per page
        offset: Pagination offset
        search: Optional email search term

    Returns:
        Tuple of (list of users, total_count, error_message)
    """
    try:
        supabase = get_admin_client()

        # Build query
        query = supabase.table("profiles").select(
            "id, email, created_at, city, is_admin",
            count="exact"
        )

        if search:
            query = query.ilike("email", f"%{search}%")

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = query.execute()

        users = result.data or []
        total = result.count or 0

        # Get plant counts for each user
        user_ids = [u["id"] for u in users]
        if user_ids:
            plants_result = (
                supabase.table("plants")
                .select("user_id")
                .in_("user_id", user_ids)
                .execute()
            )

            from collections import Counter
            plant_counts = Counter(p["user_id"] for p in (plants_result.data or []))

            for user in users:
                user["plant_count"] = plant_counts.get(user["id"], 0)

        return users, total, None

    except Exception as e:
        logger.error(f"Error getting users list: {str(e)}", exc_info=True)
        return None, 0, f"Failed to get users: {str(e)}"


def get_user_detail(user_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Get detailed info for a specific user.

    Args:
        user_id: UUID of the user

    Returns:
        Tuple of (user_detail_dict, error_message)
    """
    try:
        supabase = get_admin_client()

        # Get profile
        profile_result = (
            supabase.table("profiles")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )

        if not profile_result.data:
            return None, "User not found"

        user = profile_result.data

        # Get plant count
        plants_result = (
            supabase.table("plants")
            .select("id, name, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        user["plants"] = plants_result.data or []
        user["plant_count"] = len(plants_result.data or [])

        # Get reminder count
        reminders_result = (
            supabase.table("reminders")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
        user["reminder_count"] = reminders_result.count or 0

        # Get recent events
        events_result = (
            supabase.table("analytics_events")
            .select("event_type, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        user["recent_events"] = events_result.data or []

        return user, None

    except Exception as e:
        logger.error(f"Error getting user detail: {str(e)}", exc_info=True)
        return None, f"Failed to get user: {str(e)}"


def get_marketing_stats() -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Get marketing subscription statistics.

    Returns:
        Tuple of (stats dict, error message)

    Stats include:
    - total_subscribers: count of marketing_opt_in = True
    - total_users: total profile count
    - opt_in_rate: percentage
    - unsubscribed_count: count with marketing_unsubscribed_at set
    - welcome_emails: counts by email type
    """
    try:
        supabase = get_admin_client()

        # Get total users and subscribers
        total_result = (
            supabase.table("profiles")
            .select("id", count="exact")
            .execute()
        )
        total_users = total_result.count or 0

        subscribers_result = (
            supabase.table("profiles")
            .select("id", count="exact")
            .eq("marketing_opt_in", True)
            .execute()
        )
        total_subscribers = subscribers_result.count or 0

        # Get unsubscribed count
        unsubscribed_result = (
            supabase.table("profiles")
            .select("id", count="exact")
            .not_.is_("marketing_unsubscribed_at", "null")
            .execute()
        )
        unsubscribed_count = unsubscribed_result.count or 0

        # Calculate opt-in rate
        opt_in_rate = (
            round((total_subscribers / total_users) * 100, 1)
            if total_users > 0
            else 0
        )

        # Get welcome email counts
        welcome_emails = {"day0": 0, "day3": 0, "day7": 0}
        try:
            for email_type in ["welcome_day0", "welcome_day3", "welcome_day7"]:
                email_result = (
                    supabase.table("welcome_emails_sent")
                    .select("id", count="exact")
                    .eq("email_type", email_type)
                    .execute()
                )
                key = email_type.replace("welcome_", "")
                welcome_emails[key] = email_result.count or 0
        except Exception:
            # Table might not exist yet
            pass

        stats = {
            "total_subscribers": total_subscribers,
            "total_users": total_users,
            "opt_in_rate": opt_in_rate,
            "unsubscribed_count": unsubscribed_count,
            "welcome_emails": welcome_emails,
        }

        return stats, None

    except Exception as e:
        logger.error(f"Error getting marketing stats: {str(e)}", exc_info=True)
        return {}, f"Failed to get marketing stats: {str(e)}"


def get_marketing_activity(limit: int = 20) -> Tuple[list, Optional[str]]:
    """
    Get recent marketing-related activity.

    Returns list of recent opt-ins, opt-outs, and welcome emails sent.
    """
    try:
        supabase = get_admin_client()
        activity = []

        # Get recent subscribers (those with marketing_opt_in = True, ordered by created_at)
        # We'll approximate this by getting profiles created recently with marketing_opt_in
        subscribers_result = (
            supabase.table("profiles")
            .select("id, email, created_at, marketing_opt_in")
            .eq("marketing_opt_in", True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        if subscribers_result.data:
            for profile in subscribers_result.data:
                activity.append({
                    "type": "subscribed",
                    "email": profile.get("email", "unknown"),
                    "timestamp": profile.get("created_at"),
                })

        # Get recent unsubscribes
        unsubscribes_result = (
            supabase.table("profiles")
            .select("id, email, marketing_unsubscribed_at")
            .not_.is_("marketing_unsubscribed_at", "null")
            .order("marketing_unsubscribed_at", desc=True)
            .limit(limit)
            .execute()
        )

        if unsubscribes_result.data:
            for profile in unsubscribes_result.data:
                activity.append({
                    "type": "unsubscribed",
                    "email": profile.get("email", "unknown"),
                    "timestamp": profile.get("marketing_unsubscribed_at"),
                })

        # Get recent welcome emails sent
        try:
            emails_result = (
                supabase.table("welcome_emails_sent")
                .select("user_id, email_type, sent_at")
                .order("sent_at", desc=True)
                .limit(limit)
                .execute()
            )

            if emails_result.data:
                for email in emails_result.data:
                    activity.append({
                        "type": f"welcome_{email.get('email_type', 'unknown')}",
                        "email": email.get("user_id", "unknown")[:8] + "...",
                        "timestamp": email.get("sent_at"),
                    })
        except Exception:
            # Table might not exist yet
            pass

        # Sort by timestamp
        activity.sort(
            key=lambda x: x.get("timestamp") or "",
            reverse=True
        )

        return activity[:limit], None

    except Exception as e:
        logger.error(f"Error getting marketing activity: {str(e)}", exc_info=True)
        return [], f"Failed to get marketing activity: {str(e)}"
