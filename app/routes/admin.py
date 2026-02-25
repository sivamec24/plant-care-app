"""
Admin routes for viewing analytics and metrics.

Provides dashboard for:
- System Overview (total counts, activity feed)
- Key Metrics (Activation, WAU, MAU, Stickiness, Retention)
- User Management (list, search, detail)
- Feature Usage Analytics
- Growth Trends
- Weather API Monitoring
"""

from __future__ import annotations
import uuid
from flask import Blueprint, render_template, request
from app.utils.auth import require_admin
from app.services import analytics
from app.services.weather import get_cache_stats
from datetime import date, timedelta


def is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@require_admin
def index():
    """Admin dashboard showing all key metrics with navigation."""

    # Get all metrics
    metrics = analytics.get_all_metrics()

    # Get quick counts for overview cards
    counts = analytics.get_total_counts()

    # Calculate additional context
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)
    sixty_days_ago = today - timedelta(days=60)

    return render_template(
        "admin/index.html",
        metrics=metrics,
        counts=counts,
        today=today,
        period_start=thirty_days_ago,
        cohort_start=sixty_days_ago,
        cohort_end=thirty_days_ago,
    )


@admin_bp.route("/overview")
@require_admin
def overview():
    """System overview with quick stats and activity feed."""
    counts = analytics.get_total_counts()
    recent_events, events_error = analytics.get_recent_events(limit=20)

    return render_template(
        "admin/overview.html",
        counts=counts,
        recent_events=recent_events or [],
        events_error=events_error,
    )


@admin_bp.route("/users")
@require_admin
def users():
    """Paginated user list with search."""
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "", type=str).strip()
    per_page = 25

    offset = (page - 1) * per_page
    users_list, total, error = analytics.get_users_list(
        limit=per_page, offset=offset, search=search or None
    )

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return render_template(
        "admin/users.html",
        users=users_list or [],
        total=total,
        page=page,
        total_pages=total_pages,
        search=search,
        error=error,
    )


@admin_bp.route("/users/<user_id>")
@require_admin
def user_detail(user_id: str):
    """Detailed view for a specific user."""
    if not is_valid_uuid(user_id):
        return render_template("admin/user_detail.html", user=None, error="Invalid user ID format")

    user, error = analytics.get_user_detail(user_id)

    if error:
        return render_template("admin/user_detail.html", user=None, error=error)

    return render_template("admin/user_detail.html", user=user, error=None)


@admin_bp.route("/usage")
@require_admin
def usage():
    """Feature usage analytics."""
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    event_counts, error = analytics.get_event_counts_by_type(
        start_date=thirty_days_ago, end_date=today
    )

    # Calculate totals for key features
    ai_questions = event_counts.get("ai_question_asked", 0) if event_counts else 0
    journal_entries = event_counts.get("journal_entry_created", 0) if event_counts else 0
    reminders_created = event_counts.get("reminder_created", 0) if event_counts else 0
    reminders_completed = event_counts.get("reminder_completed", 0) if event_counts else 0

    return render_template(
        "admin/usage.html",
        event_counts=event_counts or {},
        ai_questions=ai_questions,
        journal_entries=journal_entries,
        reminders_created=reminders_created,
        reminders_completed=reminders_completed,
        period_start=thirty_days_ago,
        period_end=today,
        error=error,
    )


@admin_bp.route("/growth")
@require_admin
def growth():
    """Growth trends and signup data."""
    signups_by_week, error = analytics.get_signups_by_week(weeks=12)

    # Get WAU/MAU for context
    wau, _ = analytics.get_weekly_active_users()
    mau, _ = analytics.get_monthly_active_users()

    return render_template(
        "admin/growth.html",
        signups_by_week=signups_by_week or [],
        wau=wau,
        mau=mau,
        error=error,
    )


@admin_bp.route("/weather")
@require_admin
def weather():
    """Weather API cache monitoring."""
    cache_stats = get_cache_stats()

    return render_template(
        "admin/weather.html",
        cache_stats=cache_stats,
    )


@admin_bp.route("/marketing")
@require_admin
def marketing():
    """Marketing email metrics and subscriber overview."""
    stats, stats_error = analytics.get_marketing_stats()
    activity, activity_error = analytics.get_marketing_activity(limit=20)

    return render_template(
        "admin/marketing.html",
        stats=stats,
        activity=activity or [],
        error=stats_error or activity_error,
    )
