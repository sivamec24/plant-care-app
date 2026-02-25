"""
Authentication utilities and decorators for route protection.

Provides:
- @require_auth: Decorator to require authenticated user
- @require_premium: Decorator to require premium plan
- Session management helpers
"""

from __future__ import annotations
from datetime import datetime
from functools import wraps
from typing import Optional, Dict, Any
from flask import session, redirect, url_for, request, flash, g
from app.services import supabase_client


# ============================================================================
# Session Management
# ============================================================================

SESSION_USER_KEY = "user"
SESSION_ACCESS_TOKEN_KEY = "access_token"
SESSION_REFRESH_TOKEN_KEY = "refresh_token"


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Get currently logged-in user from session.

    Returns:
        User dict with id, email, etc. or None if not logged in
    """
    # Check if user already loaded in request context
    if hasattr(g, 'user'):
        return g.user

    # Try to get from session
    access_token = session.get(SESSION_ACCESS_TOKEN_KEY)
    refresh_token = session.get(SESSION_REFRESH_TOKEN_KEY)

    if not access_token:
        g.user = None
        return None

    # Verify token with Supabase (pass both tokens)
    user = supabase_client.verify_session(access_token, refresh_token)
    if not user:
        # Token invalid/expired, clear session
        clear_session()
        g.user = None
        return None

    # Store in request context for this request
    g.user = user
    return user


def get_current_user_id() -> Optional[str]:
    """
    Get current user's ID.

    Returns:
        User UUID or None if not logged in
    """
    user = get_current_user()
    return user.get("id") if user else None


def set_session(user: Dict[str, Any], access_token: str, refresh_token: Optional[str] = None) -> None:
    """
    Store user session data.

    Security: Regenerates session ID to prevent session fixation attacks.

    Args:
        user: User dict from Supabase Auth
        access_token: JWT access token
        refresh_token: Optional refresh token for session renewal
    """
    # Regenerate session ID to prevent session fixation
    session.clear()
    session.modified = True

    session[SESSION_USER_KEY] = {
        "id": user.get("id"),
        "email": user.get("email"),
    }
    session[SESSION_ACCESS_TOKEN_KEY] = access_token
    if refresh_token:
        session[SESSION_REFRESH_TOKEN_KEY] = refresh_token
    session.permanent = True  # Use permanent session (configurable lifetime)


def clear_session() -> None:
    """Clear user session data."""
    session.pop(SESSION_USER_KEY, None)
    session.pop(SESSION_ACCESS_TOKEN_KEY, None)
    session.pop(SESSION_REFRESH_TOKEN_KEY, None)


def is_authenticated() -> bool:
    """Check if user is currently authenticated."""
    return get_current_user() is not None


def is_admin(user_id: Optional[str]) -> bool:
    """
    Check if a user has admin privileges.

    Args:
        user_id: User UUID to check

    Returns:
        True if user is an admin, False otherwise
    """
    if not user_id:
        return False

    profile = supabase_client.get_user_profile(user_id)
    return bool(profile and profile.get("is_admin", False))


# ============================================================================
# Decorators
# ============================================================================

def require_auth(f):
    """
    Decorator to require authentication for a route.

    If user not logged in, redirects to signup page with 'next' parameter.

    Usage:
        @app.route('/dashboard')
        @require_auth
        def dashboard():
            user = get_current_user()
            return render_template('dashboard.html', user=user)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            # Store the intended destination
            next_url = request.url
            flash("Please sign in to access this page.", "info")
            return redirect(url_for("auth.signup", next=next_url))

        return f(*args, **kwargs)

    return decorated_function


def require_premium(f):
    """
    Decorator to require premium plan for a route.

    Checks if user is authenticated AND has premium access (paid or trial).
    If not premium, redirects to pricing page.

    Usage:
        @app.route('/export')
        @require_premium
        def export_plants():
            # Only premium users can access this
            return generate_pdf()
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # First check authentication
        if not is_authenticated():
            flash("Please sign in to access this page.", "info")
            return redirect(url_for("auth.signup", next=request.url))

        # Check premium access
        user_id = get_current_user_id()
        if not supabase_client.has_premium_access(user_id):
            flash("This feature requires a Premium plan. Upgrade to get unlimited access!", "warning")
            return redirect(url_for("pricing.index"))

        return f(*args, **kwargs)

    return decorated_function


def require_admin(f):
    """
    Decorator to require admin privileges for a route.

    Checks if user is authenticated AND has admin role.
    If not authenticated, redirects to signup page.
    If not admin, redirects to dashboard with access denied message.

    Usage:
        @app.route('/admin/metrics')
        @require_admin
        def admin_metrics():
            # Only admin users can access this
            return render_template('admin/metrics.html')
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # First check authentication
        if not is_authenticated():
            flash("Please sign in to access this page.", "info")
            return redirect(url_for("auth.signup", next=request.url))

        # Check admin privileges
        user_id = get_current_user_id()
        profile = supabase_client.get_user_profile(user_id)

        if not profile or not profile.get("is_admin", False):
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("dashboard.index"))

        return f(*args, **kwargs)

    return decorated_function


def optional_auth(f):
    """
    Decorator to mark a route as optionally authenticated.

    This doesn't enforce auth, but loads user if available.
    Useful for routes that work for both guests and logged-in users.

    Usage:
        @app.route('/')
        @optional_auth
        def index():
            user = get_current_user()  # May be None
            if user:
                # Show personalized content
            else:
                # Show guest content
            return render_template('index.html', user=user)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Just trigger user loading (doesn't enforce)
        get_current_user()
        return f(*args, **kwargs)

    return decorated_function


# ============================================================================
# Helper Functions for Templates
# ============================================================================

def inject_auth_context():
    """
    Context processor to inject auth data into all templates.

    Call this from the Flask app factory:
        app.context_processor(inject_auth_context)

    Makes these available in all templates:
        - current_user: User dict or None
        - is_authenticated: Boolean
        - is_premium: Boolean
        - is_in_trial: Boolean
        - trial_days_remaining: Integer
        - has_premium_access: Boolean
        - profile: User profile dict or None (includes theme_preference)
        - show_legal_banner: Boolean (True when user hasn't acknowledged latest legal update)
    """
    user = get_current_user()
    user_id = user.get("id") if user else None

    # Default values for unauthenticated users
    if not user_id:
        return {
            "current_user": None,
            "is_authenticated": False,
            "is_premium": False,
            "is_in_trial": False,
            "trial_days_remaining": 0,
            "has_premium_access": False,
            "profile": None,
            "show_legal_banner": False,
        }

    # Fetch profile once (avoids N+1 queries)
    profile = supabase_client.get_user_profile(user_id)

    # Compute premium status from profile
    is_premium = profile.get("plan") == "premium" if profile else False

    # Compute trial status from profile
    is_in_trial = False
    trial_days_remaining = 0
    if profile:
        trial_ends_at = profile.get("trial_ends_at")
        if trial_ends_at:
            try:
                trial_end = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
                now = datetime.utcnow()
                is_in_trial = now < trial_end.replace(tzinfo=None)
                if is_in_trial:
                    delta = trial_end.replace(tzinfo=None) - now
                    trial_days_remaining = max(0, delta.days)
            except Exception:
                pass

    # Check if user needs to acknowledge latest legal update
    show_legal_banner = False
    if session.get("legal_acknowledged"):
        show_legal_banner = False
    elif profile:
        ack = profile.get("legal_acknowledged_at")
        if not ack:
            show_legal_banner = True
        else:
            try:
                from flask import current_app
                legal_date = current_app.config.get("LEGAL_LAST_UPDATED", "")
                show_legal_banner = ack[:10] < legal_date
            except (TypeError, ValueError):
                show_legal_banner = True

    return {
        "current_user": user,
        "is_authenticated": True,
        "is_premium": is_premium,
        "is_in_trial": is_in_trial,
        "trial_days_remaining": trial_days_remaining,
        "has_premium_access": is_premium or is_in_trial,
        "profile": profile,
        "show_legal_banner": show_legal_banner,
    }
