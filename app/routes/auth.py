"""
Authentication routes for signup, login, and logout.

Handles:
- OTP signup/login (passwordless)
- Auth callback from Supabase
- Logout
- Current user info endpoint
"""

from __future__ import annotations
from email_validator import validate_email, EmailNotValidError
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from app.services import supabase_client
from app.utils.auth import set_session, clear_session, get_current_user, require_auth
from app.extensions import limiter


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# Whitelist of allowed redirect paths for security
ALLOWED_REDIRECT_PREFIXES = [
    '/dashboard',
    '/plants',
    '/reminders',
    '/journal',
    '/ask',
    '/pricing',
    '/admin',
]


def is_safe_redirect_url(url: str) -> bool:
    """
    Validate redirect URL for open redirect protection.

    Uses whitelist approach - only allows URLs that:
    1. Are relative (no scheme or netloc)
    2. Start with '/' but not '//'
    3. Match allowed path prefixes

    Args:
        url: URL to validate

    Returns:
        True if URL is safe to redirect to, False otherwise
    """
    if not url or not isinstance(url, str):
        return False

    from urllib.parse import urlparse
    # Parse URL
    parsed = urlparse(url)

    # Must not have scheme or netloc (prevents absolute URLs)
    if parsed.scheme or parsed.netloc:
        return False

    # Must start with / but not // (prevents protocol-relative URLs)
    if not url.startswith('/') or url.startswith('//'):
        return False

    # Must match one of the allowed prefixes
    return any(url.startswith(prefix) for prefix in ALLOWED_REDIRECT_PREFIXES)


@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config['SIGNUP_RATE_LIMIT'])  # Protect against bot signups
def signup():
    """
    Show signup form or send magic link.

    GET: Display email input form
    POST: Send magic link to email
    """
    if request.method == "GET":
        # Check if user already logged in
        if get_current_user():
            return redirect(url_for("dashboard.index"))

        # Get 'next' parameter to redirect after auth
        next_url = request.args.get("next", "")

        return render_template("auth/signup.html", next=next_url)

    # POST: Send magic link

    # Honeypot check (bot protection)
    honeypot = request.form.get("website", "")
    if honeypot:
        # Bot detected - filled the honeypot field
        current_app.logger.warning(f"Bot signup attempt blocked (honeypot filled)")
        # Pretend it worked to not reveal the honeypot
        from flask import session
        session["pending_email"] = "blocked@example.com"
        return redirect(url_for("auth.check_email"))

    # Age confirmation check (COPPA compliance)
    age_confirmed = request.form.get("age_confirmation") == "on"
    if not age_confirmed:
        flash("You must confirm you are 13 years of age or older to sign up.", "error")
        return redirect(url_for("auth.signup"))

    email = request.form.get("email", "").strip().lower()

    if not email:
        flash("Please enter your email address.", "error")
        return redirect(url_for("auth.signup"))

    # Email validation using email-validator library (RFC 5322 compliant)
    try:
        # Validate and normalize email
        valid = validate_email(email, check_deliverability=False)
        email = valid.normalized  # Use normalized form (lowercase, etc.)
    except EmailNotValidError as e:
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("auth.signup"))

    # Send OTP code via Supabase (using OTP instead of magic link to avoid spam filtering)
    result = supabase_client.send_otp_code(email)

    if result["success"]:
        # Store email and marketing preference in session for OTP verification
        from flask import session
        session["pending_email"] = email
        session["pending_marketing_opt_in"] = request.form.get("marketing_opt_in") == "on"

        # Redirect to OTP verification page
        return redirect(url_for("auth.verify_otp"))
    else:
        # Use the user-friendly error message from supabase_client
        error_message = result.get("message", "Failed to send verification code. Please try again.")
        current_app.logger.error(f"Failed to send OTP code: {result.get('error')} - {error_message}")
        flash(error_message, "error")
        return redirect(url_for("auth.signup"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Login page (same as signup for magic link auth).

    Redirects to signup since magic link works for both.
    """
    return signup()


@auth_bp.route("/check-email")
def check_email():
    """
    Show "check your email" page after magic link sent.
    (Legacy route - keeping for backward compatibility if needed)
    """
    from flask import session
    email = session.get("pending_email", "your email")

    return render_template("auth/check_email.html", email=email)


@auth_bp.route("/verify-otp", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config['SIGNUP_RATE_LIMIT'])  # Protect against brute force
def verify_otp():
    """
    Verify OTP code page.

    GET: Show OTP code input form
    POST: Verify code and create session
    """
    from flask import session

    if request.method == "GET":
        # Get email from session
        email = session.get("pending_email")
        if not email:
            flash("Please enter your email first.", "error")
            return redirect(url_for("auth.signup"))

        return render_template("auth/verify_otp.html", email=email)

    # POST: Verify OTP code
    email = session.get("pending_email")
    if not email:
        flash("Session expired. Please request a new code.", "error")
        return redirect(url_for("auth.signup"))

    code = request.form.get("code", "").strip()

    if not code:
        flash("Please enter the verification code.", "error")
        return render_template("auth/verify_otp.html", email=email)

    # Verify OTP code
    result = supabase_client.verify_otp_code(email, code)

    if not result["success"]:
        error_message = result.get("message", "Invalid code. Please try again.")
        current_app.logger.error(f"Failed to verify OTP: {result.get('error')} - {error_message}")
        flash(error_message, "error")
        return render_template("auth/verify_otp.html", email=email)

    # OTP verified successfully
    user = result["user"]
    session_data = result["session"]
    access_token = session_data["access_token"]
    refresh_token = session_data["refresh_token"]

    # Get marketing preference BEFORE set_session (which clears the session)
    marketing_opt_in = session.get("pending_marketing_opt_in", False)

    # Set session with both tokens (this clears the session)
    set_session(user, access_token, refresh_token)

    # Get or create user profile
    user_id = user.get("id")
    email = user.get("email")

    profile = supabase_client.get_user_profile(user_id)

    if not profile:
        # Profile doesn't exist (trigger should have created it, but fallback)
        current_app.logger.warning(f"Profile not found for user {user_id}, creating...")
        supabase_client.create_user_profile(user_id, email, marketing_opt_in=marketing_opt_in)
    elif marketing_opt_in and not profile.get("marketing_opt_in"):
        # User opted in during signup but profile exists without opt-in
        supabase_client.update_marketing_preference(user_id, marketing_opt_in=True)

    # Check if onboarding completed
    if not supabase_client.is_onboarding_completed(user_id):
        # Get user's plants to check if they have any
        plants = supabase_client.get_user_plants(user_id)
        if not plants or len(plants) == 0:
            flash(f"Welcome to PlantCareAI! Let's add your first plant 🌱", "success")
            return redirect(url_for("plants.onboarding"))

    # Redirect to dashboard or 'next' URL (with open redirect protection)
    next_url = request.args.get("next", "")
    if next_url and is_safe_redirect_url(next_url):
        flash(f"Welcome back!", "success")
        return redirect(next_url)  # safe: validated by is_safe_redirect_url

    # Check if this is a new signup (profile just created)
    is_new_user = profile is None

    if is_new_user:
        flash(f"Welcome to PlantCareAI!", "success")
    else:
        flash(f"Welcome back!", "success")

    return redirect(url_for("dashboard.index"))


@auth_bp.route("/callback")
def callback():
    """
    Handle magic link callback from Supabase.

    If no tokens in query params, serve the callback.html page which
    extracts tokens from URL hash and redirects back with tokens.

    If tokens present in query params (from callback.html redirect),
    verify and create session.
    """
    # Get tokens from query params (sent by JavaScript from hash)
    access_token = request.args.get("access_token")
    refresh_token = request.args.get("refresh_token")

    # If no tokens, serve the callback handler page
    if not access_token:
        return render_template("auth/callback.html")

    # Verify token and get user (pass both tokens to establish session)
    user = supabase_client.verify_session(access_token, refresh_token)

    if not user:
        flash("Authentication failed. Please try again.", "error")
        return redirect(url_for("auth.signup"))

    # Set session with both tokens
    set_session(user, access_token, refresh_token)

    # Get or create user profile
    user_id = user.get("id")
    email = user.get("email")

    profile = supabase_client.get_user_profile(user_id)

    if not profile:
        # Profile doesn't exist (trigger should have created it, but fallback)
        current_app.logger.warning(f"Profile not found for user {user_id}, creating...")
        supabase_client.create_user_profile(user_id, email)

    # Check if onboarding completed
    # TODO: Uncomment this when onboarding is implemented in Phase 3
    # if not supabase_client.is_onboarding_completed(user_id):
    #     flash(f"Welcome! Let's set up your first plant.", "success")
    #     return redirect(url_for("onboarding.step1"))

    # Redirect to dashboard or 'next' URL (with open redirect protection)
    next_url = request.args.get("next", "")
    if next_url and is_safe_redirect_url(next_url):
        flash(f"Welcome back, {email}!", "success")
        return redirect(next_url)  # safe: validated by is_safe_redirect_url

    # Check if this is a new signup (profile just created)
    is_new_user = profile is None

    if is_new_user:
        flash(f"Welcome to PlantCareAI! Let's add your first plant 🌱", "success")
    else:
        flash(f"Welcome back!", "success")

    return redirect(url_for("dashboard.index"))


@auth_bp.route("/logout")
@require_auth
def logout():
    """
    Log out current user and clear session.
    """
    supabase_client.sign_out()
    clear_session()
    flash("You've been logged out successfully.", "info")

    return redirect(url_for("auth.signup"))


@auth_bp.route("/me")
@require_auth
def me():
    """
    Get current user info as JSON (for client-side use).

    Returns:
        JSON with user info, profile, trial status
    """
    user = get_current_user()

    user_id = user.get("id")
    profile = supabase_client.get_user_profile(user_id)

    return jsonify({
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
        },
        "profile": {
            "plan": profile.get("plan") if profile else "free",
            "is_premium": supabase_client.is_premium(user_id),
            "is_in_trial": supabase_client.is_in_trial(user_id),
            "trial_days_remaining": supabase_client.trial_days_remaining(user_id),
            "has_premium_access": supabase_client.has_premium_access(user_id),
            "onboarding_completed": supabase_client.is_onboarding_completed(user_id),
        }
    })
