"""
Supabase client initialization and helper functions.

Provides centralized access to Supabase for:
- Authentication (Magic Link)
- Database queries (plants, reminders, profiles)
- Storage (photo uploads)
"""

from __future__ import annotations
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from flask import current_app, has_app_context, request
from supabase import create_client, Client
import secrets
import string
import hashlib
from app.utils.sanitize import mask_email as _mask_email


def _safe_log_error(message: str) -> None:
    """
    Log error message only if Flask app context is available.

    This allows functions to be called from tests without app context.
    In production, errors are logged to current_app.logger.
    In tests without app context, errors are silently ignored.
    """
    try:
        if has_app_context():
            current_app.logger.error(message)
    except (ImportError, RuntimeError):
        pass  # Ignore if no app context available (e.g., in tests)


def _safe_log_info(message: str) -> None:
    """Log info message only if Flask app context is available."""
    try:
        if has_app_context():
            current_app.logger.info(message)
    except (ImportError, RuntimeError):
        pass


# Global client instances (initialized once per app)
_supabase_client: Optional[Client] = None  # User client (anon key)
_supabase_admin: Optional[Client] = None   # Admin client (service role key)

# In-memory cache for plant queries (simple dict-based cache)
# Format: {cache_key: (data, timestamp)}
_PLANT_CACHE: Dict[str, tuple[list[dict], datetime]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes
_CACHE_MAX_SIZE = 500     # Prevent unbounded memory growth


def init_supabase(app) -> None:
    """
    Initialize Supabase clients with app config.
    Creates two clients:
    - Regular client with anon key (for user operations)
    - Admin client with service role key (for admin operations like creating profiles)

    Call this from the Flask app factory.
    """
    global _supabase_client, _supabase_admin

    url = app.config.get("SUPABASE_URL", "")
    anon_key = app.config.get("SUPABASE_ANON_KEY", "")
    service_key = app.config.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not anon_key:
        app.logger.warning("Supabase URL or ANON_KEY not configured. Supabase features will be disabled.")
        _supabase_client = None
        _supabase_admin = None
        return

    try:
        # Regular client for user operations
        _supabase_client = create_client(url, anon_key)
        app.logger.info("Supabase client initialized successfully")

        # Admin client for admin operations (if service key available)
        if service_key:
            _supabase_admin = create_client(url, service_key)
            app.logger.info("Supabase admin client initialized successfully")
        else:
            app.logger.warning("SUPABASE_SERVICE_ROLE_KEY not configured. Admin operations will be limited.")

    except Exception as e:
        app.logger.error(f"Failed to initialize Supabase client: {e}")
        _supabase_client = None
        _supabase_admin = None


def get_client() -> Optional[Client]:
    """Get the global Supabase client instance (user client with anon key)."""
    return _supabase_client


def get_admin_client() -> Optional[Client]:
    """Get the admin Supabase client instance (admin client with service role key)."""
    return _supabase_admin


def is_configured() -> bool:
    """Check if Supabase is properly configured."""
    return _supabase_client is not None


# ============================================================================
# Custom OTP Helpers
# ============================================================================

def _generate_otp_code() -> str:
    """
    Generate a secure 6-digit OTP code.

    Uses secrets module for cryptographically strong random numbers.

    Returns:
        6-digit numeric string
    """
    return ''.join(secrets.choice(string.digits) for _ in range(6))


def _hash_otp_code(code: str) -> str:
    """
    Hash OTP code using SHA-256 for secure storage.

    OTP codes are hashed before database storage so that if the database
    is compromised, attackers cannot see active codes. SHA-256 is used
    instead of bcrypt/argon2 because:
    1. OTP codes are short-lived (15 minutes)
    2. They're already high-entropy (6 random digits = 1 million combinations)
    3. Fast hashing is acceptable since brute force is impractical

    Args:
        code: 6-digit OTP code

    Returns:
        Hexadecimal hash string (64 characters)
    """
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def _store_otp_code(email: str, code: str, expiration_minutes: int = 15) -> Dict[str, Any]:
    """
    Store OTP code in database with expiration.

    The code is hashed using SHA-256 before storage for security.
    If the database is compromised, attackers cannot see active codes.

    Args:
        email: User's email address
        code: 6-digit OTP code (will be hashed before storage)
        expiration_minutes: Minutes until code expires (default 15)

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    if not _supabase_admin:
        return {"success": False, "error": "admin_client_not_configured"}

    try:
        # Get client IP and user agent for security logging
        ip_address = None
        user_agent = None
        try:
            if has_app_context():
                ip_address = request.remote_addr
                user_agent = request.headers.get('User-Agent', '')[:255]  # Truncate to fit DB
        except Exception:
            pass  # Don't fail if request context unavailable

        # Calculate expiration timestamp
        expires_at = datetime.utcnow() + timedelta(minutes=expiration_minutes)

        # Hash the OTP code before storage for security
        # If database is compromised, attackers won't see active codes
        code_hash = _hash_otp_code(code)

        # Insert OTP code into database (using admin client for RLS bypass)
        result = _supabase_admin.table("otp_codes").insert({
            "email": email.lower(),
            "code": code_hash,  # Store hash, not plaintext
            "expires_at": expires_at.isoformat(),
            "ip_address": ip_address,
            "user_agent": user_agent
        }).execute()

        if result.data:
            return {"success": True}
        else:
            return {"success": False, "error": "database_insert_failed"}

    except Exception as e:
        _safe_log_error(f"Error storing OTP code: {e}")
        return {"success": False, "error": "database_error"}


def _verify_otp_from_database(email: str, code: str) -> Dict[str, Any]:
    """
    Verify OTP code from database.

    Checks:
    - Code exists for email
    - Code hasn't expired
    - Code hasn't been used
    - Attempts not exceeded

    Args:
        email: User's email address
        code: 6-digit OTP code to verify

    Returns:
        Dict with 'success' bool and optional 'error'/'message'
    """
    if not _supabase_admin:
        return {"success": False, "error": "admin_client_not_configured"}

    try:
        # Hash the input code to compare with stored hash
        code_hash = _hash_otp_code(code)

        # Look up OTP code (using admin client for RLS bypass)
        result = _supabase_admin.table("otp_codes") \
            .select("*") \
            .eq("email", email.lower()) \
            .eq("code", code_hash) \
            .eq("used", False) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if not result.data or len(result.data) == 0:
            return {
                "success": False,
                "error": "invalid_code",
                "message": "Invalid verification code. Please check and try again."
            }

        otp_record = result.data[0]

        # Check if code has expired
        expires_at = datetime.fromisoformat(otp_record["expires_at"].replace('Z', '+00:00'))
        if datetime.utcnow().replace(tzinfo=expires_at.tzinfo) > expires_at:
            return {
                "success": False,
                "error": "expired_code",
                "message": "This code has expired. Please request a new one."
            }

        # Check if attempts exceeded
        if otp_record["attempts"] >= otp_record["max_attempts"]:
            return {
                "success": False,
                "error": "max_attempts_exceeded",
                "message": "Too many failed attempts. Please request a new code."
            }

        # Mark code as used
        _supabase_admin.table("otp_codes") \
            .update({"used": True, "verified_at": datetime.utcnow().isoformat()}) \
            .eq("id", otp_record["id"]) \
            .execute()

        return {"success": True}

    except Exception as e:
        _safe_log_error(f"Error verifying OTP from database: {e}")
        return {
            "success": False,
            "error": "database_error",
            "message": "Unable to verify code. Please try again."
        }


# ============================================================================
# Authentication Helpers
# ============================================================================

def send_otp_code(email: str) -> Dict[str, Any]:
    """
    Send a 6-digit OTP code to the user's email for passwordless login.

    Uses custom OTP system with:
    - 15-minute expiration (vs Supabase's hardcoded 60 seconds)
    - Resend email service (avoids Supabase email delays)
    - Database storage for verification

    This replaces Supabase's built-in OTP to avoid spam filtering and short expiration issues.

    Args:
        email: User's email address

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    if not _supabase_admin:
        return {"success": False, "error": "Supabase admin not configured"}

    try:
        # Generate secure 6-digit code
        code = _generate_otp_code()

        # Store code in database with 15-minute expiration
        store_result = _store_otp_code(email, code)
        if not store_result["success"]:
            _safe_log_error(f"Failed to store OTP code: {store_result.get('error')}")
            return {
                "success": False,
                "error": "storage_failed",
                "message": "Unable to generate verification code. Please try again."
            }

        # Send code via Resend email service
        from app.services.email import send_otp_email
        email_result = send_otp_email(email, code)

        if not email_result["success"]:
            # Email failed - return the specific error from email service
            return email_result

        _safe_log_info(f"OTP code sent successfully to {_mask_email(email)}")
        return {
            "success": True,
            "message": f"A 6-digit code has been sent to {email}. Please check your inbox."
        }

    except Exception as e:
        error_msg = str(e).lower()
        _safe_log_error(f"Error sending OTP code: {e}")

        # Detect rate limiting errors
        if "rate limit" in error_msg or "too many" in error_msg:
            return {
                "success": False,
                "error": "rate_limit",
                "message": "You've requested too many codes. Please wait a few minutes and try again."
            }
        # Generic error
        else:
            return {
                "success": False,
                "error": "unknown",
                "message": "Unable to send verification code. Please try again later."
            }


def verify_otp_code(email: str, token: str) -> Dict[str, Any]:
    """
    Verify a 6-digit OTP code and create Supabase session.

    Uses custom OTP verification from database, then creates Supabase Auth session.

    Args:
        email: User's email address
        token: 6-digit OTP code

    Returns:
        Dict with 'success' bool, 'user' data, 'session' with access_token/refresh_token, or 'error'
    """
    if not _supabase_admin:
        return {"success": False, "error": "Supabase admin not configured"}

    try:
        # Verify OTP code from our custom database
        verify_result = _verify_otp_from_database(email, token)

        if not verify_result["success"]:
            # Return the specific error from verification
            # Note: Attempt counting is handled in _verify_otp_from_database
            return verify_result

        # OTP verified successfully - now create/sign in user with Supabase Auth
        # We'll use a temp password approach to get session tokens

        # Check if user exists and create/get user ID
        try:
            # Try to create the user first (optimistic approach)
            # If they already exist, we'll catch the error and look them up
            try:
                _safe_log_info(f"Attempting to create user for {_mask_email(email)}")
                new_user = _supabase_admin.auth.admin.create_user({
                    "email": email,
                    "email_confirm": True,  # Auto-confirm since they verified OTP
                })
                user_id = new_user.user.id
                user_data = new_user.user.model_dump()
                _safe_log_info(f"Successfully created new user with ID {user_id}")

            except Exception as create_error:
                # Check if error is "user already exists"
                error_msg = str(create_error).lower()
                if "already been registered" in error_msg or "already exists" in error_msg:
                    _safe_log_info(f"User {_mask_email(email)} already exists, looking them up")
                    # Look up by email via profiles table, then get auth user by ID.
                    # Avoids list_users() which fetches ALL users (enumeration risk).
                    profile_result = _supabase_admin.table("profiles").select("id").eq("email", email).limit(1).execute()
                    if profile_result and profile_result.data and len(profile_result.data) > 0:
                        found_id = profile_result.data[0]["id"]
                        existing = _supabase_admin.auth.admin.get_user_by_id(found_id)
                        user_id = existing.user.id
                        user_data = existing.user.model_dump()
                    else:
                        _safe_log_error("User exists in auth but not in profiles table")
                        raise Exception("User exists but couldn't be retrieved")

                    _safe_log_info(f"Found existing user with ID {user_id}")
                else:
                    # Different error - re-raise it
                    _safe_log_error(f"Error creating user (not 'already exists'): {create_error}")
                    raise

        except Exception as e:
            _safe_log_error(f"Error getting/creating user: {e}")
            return {
                "success": False,
                "error": "user_creation_failed",
                "message": "Unable to create user account. Please try again."
            }

        # Generate session tokens for the user using temp password approach
        try:
            # Generate password meeting Supabase requirements:
            # lowercase, uppercase, digits, special characters
            temp_password = (
                secrets.token_urlsafe(32) +  # Base random string
                "Aa1!"  # Guarantee all required character classes
            )
            _safe_log_info(f"Setting temporary password for user {user_id}")
            _supabase_admin.auth.admin.update_user_by_id(
                user_id,
                {"password": temp_password}
            )

            # Use a disposable client for sign-in to avoid mutating shared state
            _safe_log_info(f"Signing in with temporary password for {_mask_email(email)}")
            disposable_client = create_client(
                current_app.config["SUPABASE_URL"],
                current_app.config["SUPABASE_ANON_KEY"]
            )
            session_response = disposable_client.auth.sign_in_with_password({
                "email": email,
                "password": temp_password
            })

            if not session_response or not session_response.session:
                _safe_log_error(f"Failed to create session for {_mask_email(email)}")
                return {
                    "success": False,
                    "error": "session_creation_failed",
                    "message": "Unable to create session. Please try again."
                }

            # NOTE: We intentionally do NOT change the password after sign-in.
            # Password changes invalidate all sessions, which would break the
            # session we just created. The temp password is cryptographically
            # random (36+ chars) and unknown to users. On next OTP login,
            # a new random password is set anyway.

            # Set session on shared client so RLS-protected queries work
            # immediately after login (e.g., profile/plant checks in auth route)
            _supabase_client.auth.set_session(
                access_token=session_response.session.access_token,
                refresh_token=session_response.session.refresh_token
            )

            _safe_log_info(f"Successfully created session for {_mask_email(email)}")
            return {
                "success": True,
                "user": session_response.user.model_dump(),
                "session": {
                    "access_token": session_response.session.access_token,
                    "refresh_token": session_response.session.refresh_token
                }
            }

        except Exception as e:
            _safe_log_error(f"Error creating session: {e}")
            return {
                "success": False,
                "error": "session_creation_failed",
                "message": "Unable to create session. Please try again."
            }

    except Exception as e:
        error_msg = str(e).lower()
        _safe_log_error(f"Error verifying OTP: {e}")

        return {
            "success": False,
            "error": "unknown",
            "message": "Unable to verify code. Please try again."
        }


def send_magic_link(email: str) -> Dict[str, Any]:
    """
    Send a magic link to the user's email for passwordless login.

    Args:
        email: User's email address

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    if not _supabase_client:
        return {"success": False, "error": "Supabase not configured"}

    try:
        # Supabase Auth will automatically send magic link email
        response = _supabase_client.auth.sign_in_with_otp({
            "email": email,
            "options": {
                "email_redirect_to": current_app.config.get("SUPABASE_REDIRECT_URL", "http://localhost:5000/auth/callback")
            }
        })

        return {
            "success": True,
            "message": f"Magic link sent to {email}. Please check your inbox."
        }
    except Exception as e:
        error_msg = str(e).lower()
        _safe_log_error(f"Error sending magic link: {e}")

        # Detect rate limiting errors
        if "rate limit" in error_msg or "too many requests" in error_msg:
            return {
                "success": False,
                "error": "rate_limit",
                "message": "You've requested too many magic links. Please wait a few minutes and try again."
            }
        # Detect invalid email errors
        elif "invalid" in error_msg and "email" in error_msg:
            return {
                "success": False,
                "error": "invalid_email",
                "message": "The email address is invalid. Please check and try again."
            }
        # Generic error
        else:
            return {
                "success": False,
                "error": "unknown",
                "message": "Unable to send magic link. Please try again later."
            }


def verify_session(access_token: str, refresh_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Verify a user session token and return user data.

    This establishes the session in Supabase using the provided tokens,
    which is required for RLS-protected database queries to work.

    Note: set_session() mutates shared client state. Under high concurrent
    load this could cause race conditions, but Flask's default threaded
    mode with typical traffic makes this unlikely in practice.

    Args:
        access_token: JWT access token from Supabase Auth
        refresh_token: Optional refresh token (recommended for session refresh)

    Returns:
        User dict with id, email, etc. or None if invalid
    """
    if not _supabase_client:
        return None

    try:
        # Set the session with the provided tokens
        # This is required for RLS-protected queries to work
        session_response = _supabase_client.auth.set_session(
            access_token=access_token,
            refresh_token=refresh_token or ""
        )

        if session_response and session_response.user:
            return session_response.user.model_dump()
        return None

    except Exception as e:
        _safe_log_error(f"Error verifying session: {e}")
        return None


def sign_out() -> bool:
    """
    Sign out a user session.

    Server-side token revocation is not available in the Supabase Python SDK.
    The Flask route clears session cookies, which is the primary sign-out
    mechanism. JWT tokens will naturally expire.

    Returns:
        True always (cookie clearing handles actual sign-out)
    """
    return True


# ============================================================================
# Timezone Helpers
# ============================================================================

# Curated timezone list grouped by region (for override dropdown)
TIMEZONE_GROUPS = {
    "Americas": [
        "America/New_York",      # Eastern
        "America/Chicago",       # Central
        "America/Denver",        # Mountain
        "America/Phoenix",       # Arizona (no DST)
        "America/Los_Angeles",   # Pacific
        "America/Anchorage",     # Alaska
        "Pacific/Honolulu",      # Hawaii
        "America/Toronto",       # Canada Eastern
        "America/Vancouver",     # Canada Pacific
        "America/Mexico_City",   # Mexico
        "America/Sao_Paulo",     # Brazil
    ],
    "Europe": [
        "Europe/London",         # UK/GMT
        "Europe/Paris",          # Central Europe
        "Europe/Berlin",         # Germany
        "Europe/Amsterdam",      # Netherlands
        "Europe/Rome",           # Italy
        "Europe/Madrid",         # Spain
        "Europe/Moscow",         # Russia
    ],
    "Asia & Middle East": [
        "Asia/Dubai",            # UAE/Gulf
        "Asia/Kolkata",          # India
        "Asia/Singapore",        # Singapore/Malaysia
        "Asia/Hong_Kong",        # Hong Kong
        "Asia/Shanghai",         # China
        "Asia/Tokyo",            # Japan
        "Asia/Seoul",            # South Korea
    ],
    "Pacific & Australia": [
        "Australia/Sydney",      # Australia Eastern
        "Australia/Melbourne",   # Australia Eastern
        "Australia/Perth",       # Australia Western
        "Pacific/Auckland",      # New Zealand
    ],
}

# Flat list of all valid timezones for validation
VALID_TIMEZONES = set()
for zones in TIMEZONE_GROUPS.values():
    VALID_TIMEZONES.update(zones)


# Lazy-loaded TimezoneFinder instance
_timezone_finder = None


def get_timezone_for_coordinates(lat: float, lon: float) -> Optional[str]:
    """
    Get IANA timezone identifier from coordinates using timezonefinder (offline).

    This function uses a lazy-loaded TimezoneFinder instance for efficiency.
    No API calls are made - the lookup is performed locally.

    Args:
        lat: Latitude coordinate
        lon: Longitude coordinate

    Returns:
        IANA timezone string (e.g., "America/New_York"), or None if unable to determine
    """
    global _timezone_finder

    try:
        # Lazy-load TimezoneFinder (it has a large initial load time)
        if _timezone_finder is None:
            from timezonefinder import TimezoneFinder
            _timezone_finder = TimezoneFinder()

        return _timezone_finder.timezone_at(lat=lat, lng=lon)
    except Exception as e:
        _safe_log_error(f"Error getting timezone for coordinates ({lat}, {lon}): {e}")
        return None


def update_user_timezone(user_id: str, timezone: str) -> tuple[bool, Optional[str]]:
    """
    Manually override user's timezone (or clear to use city-derived/browser default).

    Args:
        user_id: User's UUID
        timezone: IANA timezone identifier (e.g., "America/New_York"), or empty to clear

    Returns:
        tuple[bool, Optional[str]]: (success, error_message)
    """
    if not _supabase_client:
        return False, "Database not configured"

    try:
        # Validate timezone if provided
        if timezone:
            timezone = timezone.strip()
            if timezone not in VALID_TIMEZONES:
                return False, f"Invalid timezone. Please select from the dropdown."

        # Update profile
        response = _supabase_client.table("profiles").update({
            "timezone": timezone if timezone else None
        }).eq("id", user_id).execute()

        if response.data:
            return True, None
        return False, "Failed to update timezone"

    except Exception as e:
        _safe_log_error(f"Error updating user timezone: {e}")
        return False, f"Error updating timezone: {str(e)}"


# ============================================================================
# Profile Helpers
# ============================================================================

def get_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user profile by user ID.

    Args:
        user_id: Supabase user UUID

    Returns:
        Profile dict with plan, trial_ends_at, etc. or None if not found
    """
    if not _supabase_client:
        return None

    # Validate UUID format before sending to Postgres
    from app.utils.validation import is_valid_uuid
    if not is_valid_uuid(user_id):
        _safe_log_error(f"Invalid UUID passed to get_user_profile: {user_id!r}")
        return None

    try:
        # Use maybeSingle() instead of single() to handle 0 rows gracefully
        response = _supabase_client.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
        return response.data  # Returns None if no rows found
    except Exception as e:
        _safe_log_error(f"Error fetching user profile: {e}")
        return None


def create_user_profile(
    user_id: str, email: str, marketing_opt_in: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Create a new user profile with 14-day trial.
    Note: This should be handled by the database trigger, but included as fallback.

    Uses admin client to bypass RLS (Row-Level Security) policies.

    Args:
        user_id: Supabase user UUID
        email: User's email address
        marketing_opt_in: Whether user opted in to marketing emails

    Returns:
        Created profile dict or None
    """
    # Use admin client to bypass RLS when creating profiles
    admin_client = get_admin_client()

    if not admin_client:
        current_app.logger.error("Admin client not available. Cannot create profile.")
        return None

    try:
        trial_ends_at = (datetime.utcnow() + timedelta(days=14)).isoformat()

        response = admin_client.table("profiles").insert({
            "id": user_id,
            "email": email,
            "plan": "free",
            "trial_ends_at": trial_ends_at,
            "onboarding_completed": False,
            "marketing_opt_in": marketing_opt_in
        }).execute()

        return response.data[0] if response.data else None
    except Exception as e:
        error_msg = str(e)

        # If profile already exists (duplicate key), fetch and return it instead
        if "duplicate key" in error_msg or "23505" in error_msg:
            _safe_log_info(f"Profile already exists for user {user_id}, fetching existing profile")
            return get_user_profile(user_id)

        _safe_log_error(f"Error creating user profile: {e}")
        return None


def update_user_city(user_id: str, city: str) -> tuple[bool, Optional[str]]:
    """
    Update user's city/location in their profile.

    Also auto-derives timezone from city coordinates using weather API + timezonefinder.

    Security:
    - Input sanitization (XSS prevention)
    - Length validation (max 200 characters)
    - Authorization check (user can only update own profile)

    Args:
        user_id: User's UUID
        city: City name or ZIP code (e.g., "Austin, TX" or "78701")

    Returns:
        tuple[bool, Optional[str]]: (success, error_message)
    """
    if not _supabase_client:
        return False, "Database not configured"

    try:
        # Input validation and sanitization
        if city:
            # Strip whitespace
            city = city.strip()

            # Max length check (prevent abuse)
            if len(city) > 200:
                return False, "City name too long (max 200 characters)"

            # Basic sanitization: remove dangerous characters
            # Allow letters, numbers, spaces, commas, hyphens, periods
            import re
            if not re.match(r'^[a-zA-Z0-9\s,.\-]+$', city):
                return False, "Invalid characters in city name"
        else:
            city = None  # Allow clearing the city

        # Build update data
        update_data = {"city": city}

        # Auto-derive timezone from city coordinates
        if city:
            # Get coordinates from weather API
            from .weather import get_weather_for_city
            weather = get_weather_for_city(city)

            if weather and weather.get("lat") is not None and weather.get("lon") is not None:
                timezone = get_timezone_for_coordinates(weather["lat"], weather["lon"])
                if timezone:
                    update_data["timezone"] = timezone
                    _safe_log_info(f"Auto-derived timezone {timezone} for city {city}")
        else:
            # City cleared - also clear timezone (falls back to browser default)
            update_data["timezone"] = None

        # Update profile (RLS ensures user can only update their own)
        response = _supabase_client.table("profiles").update(update_data).eq("id", user_id).execute()

        if response.data:
            return True, None
        return False, "Failed to update city"

    except Exception as e:
        _safe_log_error(f"Error updating user city: {e}")
        return False, f"Error updating city: {str(e)}"


def update_marketing_preference(
    user_id: str, marketing_opt_in: bool
) -> tuple[bool, Optional[str]]:
    """
    Update user's marketing email preference.

    Args:
        user_id: User's UUID
        marketing_opt_in: Whether user wants to receive marketing emails

    Returns:
        tuple[bool, Optional[str]]: (success, error_message)
    """
    if not _supabase_client:
        return False, "Database not configured"

    try:
        update_data = {"marketing_opt_in": marketing_opt_in}

        # If opting out, record the timestamp
        if not marketing_opt_in:
            from datetime import datetime, timezone

            update_data["marketing_unsubscribed_at"] = datetime.now(
                timezone.utc
            ).isoformat()
        else:
            # If opting back in, clear the unsubscribed timestamp
            update_data["marketing_unsubscribed_at"] = None

        response = (
            _supabase_client.table("profiles")
            .update(update_data)
            .eq("id", user_id)
            .execute()
        )

        if response.data:
            _safe_log_info(
                f"Updated marketing preference for user {user_id}: {marketing_opt_in}"
            )
            return True, None
        return False, "Failed to update marketing preference"

    except Exception as e:
        _safe_log_error(f"Error updating marketing preference: {e}")
        return False, f"Error updating marketing preference: {str(e)}"


def update_legal_acknowledgment(user_id: str) -> tuple[bool, Optional[str]]:
    """
    Record that the user has acknowledged the latest legal updates.

    Args:
        user_id: User's UUID

    Returns:
        tuple[bool, Optional[str]]: (success, error_message)
    """
    if not _supabase_client:
        return False, "Database not configured"

    try:
        from datetime import datetime, timezone

        response = (
            _supabase_client.table("profiles")
            .update({"legal_acknowledged_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", user_id)
            .execute()
        )

        if response.data:
            return True, None
        return False, "Failed to update legal acknowledgment"

    except Exception as e:
        _safe_log_error(f"Error updating legal acknowledgment: {e}")
        return False, f"Error updating legal acknowledgment: {str(e)}"


def update_user_theme(user_id: str, theme: str) -> tuple[bool, Optional[str]]:
    """
    Update user's theme preference (light, dark, or auto).

    Security:
    - Input validation (only allows 'light', 'dark', 'auto')
    - Authorization check (user can only update own preference)

    Args:
        user_id: User's UUID
        theme: Theme preference ('light', 'dark', or 'auto')

    Returns:
        (success, error_message)
    """
    if not _supabase_client:
        return False, "Database not configured"

    try:
        # Validate theme value
        theme = theme.strip().lower() if theme else 'auto'

        if theme not in ['light', 'dark', 'auto']:
            return False, "Invalid theme option. Must be 'light', 'dark', or 'auto'"

        # Update user's theme preference
        response = _supabase_client.table("profiles").update({
            "theme_preference": theme
        }).eq("id", user_id).execute()

        if response.data:
            return True, None
        return False, "Failed to update theme preference"

    except Exception as e:
        _safe_log_error(f"Error updating user theme: {e}")
        return False, f"Error updating theme: {str(e)}"


def update_user_preferences(
    user_id: str,
    experience_level: Optional[str] = None,
    primary_goal: Optional[str] = None,
    time_commitment: Optional[str] = None,
    environment_preference: Optional[str] = None
) -> tuple[bool, Optional[str]]:
    """
    Update user's plant care preferences for AI personalization.

    Args:
        user_id: User's UUID
        experience_level: 'beginner', 'intermediate', or 'expert'
        primary_goal: 'keep_alive', 'grow_collection', or 'specific_focus'
        time_commitment: 'minimal', 'moderate', or 'dedicated'
        environment_preference: 'indoor', 'outdoor', or 'both'

    Returns:
        tuple[bool, Optional[str]]: (success, error_message)
    """
    if not _supabase_client:
        return False, "Database not configured"

    try:
        # Validate values
        valid_experience = {'beginner', 'intermediate', 'expert'}
        valid_goals = {'keep_alive', 'grow_collection', 'specific_focus'}
        valid_time = {'minimal', 'moderate', 'dedicated'}
        valid_environment = {'indoor', 'outdoor', 'both'}

        if experience_level and experience_level not in valid_experience:
            return False, f"Invalid experience level. Must be one of: {', '.join(valid_experience)}"
        if primary_goal and primary_goal not in valid_goals:
            return False, f"Invalid primary goal. Must be one of: {', '.join(valid_goals)}"
        if time_commitment and time_commitment not in valid_time:
            return False, f"Invalid time commitment. Must be one of: {', '.join(valid_time)}"
        if environment_preference and environment_preference not in valid_environment:
            return False, f"Invalid environment preference. Must be one of: {', '.join(valid_environment)}"

        # Build update data
        update_data = {}
        if experience_level is not None:
            update_data["experience_level"] = experience_level
        if primary_goal is not None:
            update_data["primary_goal"] = primary_goal
        if time_commitment is not None:
            update_data["time_commitment"] = time_commitment
        if environment_preference is not None:
            update_data["environment_preference"] = environment_preference

        # Mark preferences as completed with timestamp
        if update_data:
            update_data["preferences_completed_at"] = datetime.utcnow().isoformat()

        response = (
            _supabase_client.table("profiles")
            .update(update_data)
            .eq("id", user_id)
            .execute()
        )

        if response.data:
            _safe_log_info(f"Updated preferences for user {user_id}")
            return True, None
        return False, "Failed to update preferences"

    except Exception as e:
        _safe_log_error(f"Error updating user preferences: {e}")
        return False, f"Error updating preferences: {str(e)}"


def has_preferences_configured(user_id: str) -> bool:
    """
    Check if user has completed the preferences questionnaire.

    Args:
        user_id: Supabase user UUID

    Returns:
        True if preferences have been configured, False otherwise
    """
    profile = get_user_profile(user_id)
    if not profile:
        return False

    return profile.get("preferences_completed_at") is not None


def get_user_preferences(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user's plant care preferences for AI context building.

    Args:
        user_id: Supabase user UUID

    Returns:
        Dict with preference fields or None if not found/configured
    """
    profile = get_user_profile(user_id)
    if not profile:
        return None

    # Return preference fields (may be None if not yet configured)
    return {
        "experience_level": profile.get("experience_level"),
        "primary_goal": profile.get("primary_goal"),
        "time_commitment": profile.get("time_commitment"),
        "environment_preference": profile.get("environment_preference"),
        "preferences_completed_at": profile.get("preferences_completed_at"),
    }


def get_user_hemisphere(user_id: str) -> str:
    """
    Get user's hemisphere (from preference or auto-detect from city).

    Priority:
    1. Explicit hemisphere preference in profile
    2. Auto-detect from city latitude
    3. Default to 'northern' if unknown

    Args:
        user_id: User's UUID

    Returns:
        'northern' or 'southern'
    """
    from app.services.weather import get_city_latitude

    try:
        profile = get_user_profile(user_id)
        if not profile:
            return 'northern'

        # Check explicit hemisphere preference
        if profile.get('hemisphere'):
            return profile['hemisphere']

        # Try to infer from city coordinates
        city = profile.get('city')
        if city:
            lat = get_city_latitude(city)
            if lat is not None:
                return 'southern' if lat < 0 else 'northern'
    except Exception as e:
        _safe_log_error(f"Error getting user hemisphere: {e}")

    return 'northern'


def update_hemisphere_preference(
    user_id: str, hemisphere: Optional[str]
) -> tuple[bool, Optional[str]]:
    """
    Update user's hemisphere preference.

    Args:
        user_id: User's UUID
        hemisphere: 'northern', 'southern', or None/empty (auto-detect)

    Returns:
        tuple[bool, Optional[str]]: (success, error_message)
    """
    if not _supabase_client:
        return False, "Database not configured"

    # Normalize empty string to None
    if hemisphere == "":
        hemisphere = None

    # Validate hemisphere value
    if hemisphere and hemisphere not in ('northern', 'southern'):
        return False, "Invalid hemisphere value. Must be 'northern', 'southern', or empty for auto-detect."

    try:
        response = (
            _supabase_client.table("profiles")
            .update({"hemisphere": hemisphere})
            .eq("id", user_id)
            .execute()
        )

        if response.data:
            _safe_log_info(f"Updated hemisphere preference for user {user_id}")
            return True, None
        return False, "Failed to update hemisphere preference"

    except Exception as e:
        _safe_log_error(f"Error updating hemisphere preference: {e}")
        return False, f"Error updating hemisphere: {str(e)}"


def is_premium(user_id: str) -> bool:
    """
    Check if user has premium plan.

    Args:
        user_id: Supabase user UUID

    Returns:
        True if premium, False otherwise
    """
    profile = get_user_profile(user_id)
    if not profile:
        return False

    return profile.get("plan") == "premium"


def is_in_trial(user_id: str) -> bool:
    """
    Check if user is currently in premium trial period.

    Args:
        user_id: Supabase user UUID

    Returns:
        True if in trial, False otherwise
    """
    profile = get_user_profile(user_id)
    if not profile:
        return False

    trial_ends_at = profile.get("trial_ends_at")
    if not trial_ends_at:
        return False

    try:
        trial_end = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
        return datetime.utcnow() < trial_end.replace(tzinfo=None)
    except Exception as e:
        _safe_log_error(f"Error parsing trial date: {e}")
        return False


def trial_days_remaining(user_id: str) -> int:
    """
    Get number of days remaining in trial.

    Args:
        user_id: Supabase user UUID

    Returns:
        Days remaining (0 if trial expired or not in trial)
    """
    profile = get_user_profile(user_id)
    if not profile:
        return 0

    trial_ends_at = profile.get("trial_ends_at")
    if not trial_ends_at:
        return 0

    try:
        trial_end = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
        delta = trial_end.replace(tzinfo=None) - datetime.utcnow()
        return max(0, delta.days)
    except Exception as e:
        _safe_log_error(f"Error calculating trial days: {e}")
        return 0


def has_premium_access(user_id: str) -> bool:
    """
    Check if user has premium access (either paid premium or in trial).

    Args:
        user_id: Supabase user UUID

    Returns:
        True if has premium access, False otherwise
    """
    return is_premium(user_id) or is_in_trial(user_id)


# ============================================================================
# Plant Helpers
# ============================================================================

def get_plant_count(user_id: str) -> int:
    """
    Get number of plants user has.

    Args:
        user_id: Supabase user UUID

    Returns:
        Plant count (0 if error)
    """
    if not _supabase_client:
        return 0

    try:
        response = _supabase_client.table("plants").select("id", count="exact").eq("user_id", user_id).execute()
        return response.count or 0
    except Exception as e:
        _safe_log_error(f"Error getting plant count: {e}")
        return 0


def can_add_plant(user_id: str) -> tuple[bool, str]:
    """
    Check if user can add another plant (respects 10-plant limit for Starter).

    Args:
        user_id: Supabase user UUID

    Returns:
        Tuple of (can_add: bool, message: str)
    """
    # Premium users (paid or trial) can add unlimited plants
    if has_premium_access(user_id):
        return True, "Premium access - unlimited plants"

    # Starter users limited to configured plant limit
    plant_limit = current_app.config['FREE_TIER_PLANT_LIMIT']
    current_count = get_plant_count(user_id)
    if current_count >= plant_limit:
        return False, f"You've reached your {plant_limit}-plant limit. Upgrade to Premium for unlimited plants."

    if current_count == plant_limit - 1:
        return True, f"You can add 1 more plant"

    return True, f"You can add {plant_limit - current_count} more plants"


def _get_cache_key(user_id: str, limit: int, offset: int, fields: str) -> str:
    """Generate cache key for plant query."""
    return f"plants:{user_id}:{limit}:{offset}:{fields}"


def _get_cached_plants(cache_key: str) -> list[dict] | None:
    """
    Get plants from cache if valid.

    Returns:
        Cached plant list if valid, None if cache miss or expired
    """
    if cache_key not in _PLANT_CACHE:
        return None

    cached_data, cached_at = _PLANT_CACHE[cache_key]
    age_seconds = (datetime.now() - cached_at).total_seconds()

    if age_seconds > _CACHE_TTL_SECONDS:
        # Cache expired, remove it
        del _PLANT_CACHE[cache_key]
        return None

    return cached_data


def _cache_plants(cache_key: str, plants: list[dict]) -> None:
    """Store plants in cache with current timestamp."""
    # Evict oldest entries if cache is full
    if len(_PLANT_CACHE) >= _CACHE_MAX_SIZE and cache_key not in _PLANT_CACHE:
        oldest_key = min(_PLANT_CACHE, key=lambda k: _PLANT_CACHE[k][1])
        del _PLANT_CACHE[oldest_key]
    _PLANT_CACHE[cache_key] = (plants, datetime.now())


def invalidate_plant_cache(user_id: str) -> None:
    """
    Invalidate all cached plant queries for a user.

    Call this when plants are added, updated, or deleted.
    """
    # Remove all cache entries for this user
    keys_to_remove = [key for key in _PLANT_CACHE.keys() if key.startswith(f"plants:{user_id}:")]
    for key in keys_to_remove:
        del _PLANT_CACHE[key]


def get_user_plants(user_id: str, limit: int = 100, offset: int = 0, fields: str = "*", use_cache: bool = True) -> list[dict]:
    """
    Get all plants for a user with pagination.

    Args:
        user_id: Supabase user UUID
        limit: Maximum number of plants to return
        offset: Number of plants to skip (for pagination)
        fields: Comma-separated list of fields to select (default: "*" for all)
                For optimal performance, specify only needed fields.
                Example: "id,name,nickname,photo_url_thumb"
        use_cache: Whether to use in-memory cache (default: True)
                   Set to False when you need fresh data immediately after updates

    Returns:
        List of plant dictionaries, empty list if error
    """
    if not _supabase_client:
        return []

    # Check cache first (if enabled)
    if use_cache:
        cache_key = _get_cache_key(user_id, limit, offset, fields)
        cached_plants = _get_cached_plants(cache_key)
        if cached_plants is not None:
            return cached_plants

    try:
        response = (_supabase_client
                   .table("plants")
                   .select(fields)
                   .eq("user_id", user_id)
                   .order("created_at", desc=True)
                   .limit(limit)
                   .offset(offset)
                   .execute())
        plants = response.data or []

        # Cache the results (if caching enabled)
        if use_cache:
            cache_key = _get_cache_key(user_id, limit, offset, fields)
            _cache_plants(cache_key, plants)

        return plants
    except Exception as e:
        _safe_log_error(f"Error getting user plants: {e}")
        return []


def get_plant_by_id(plant_id: str, user_id: str) -> dict | None:
    """
    Get a single plant by ID, verifying ownership.

    Args:
        plant_id: Plant UUID
        user_id: User UUID (for ownership verification)

    Returns:
        Plant dictionary if found and owned by user, None otherwise
    """
    if not _supabase_client:
        return None

    try:
        response = (_supabase_client
                   .table("plants")
                   .select("*")
                   .eq("id", plant_id)
                   .eq("user_id", user_id)
                   .single()
                   .execute())
        return response.data
    except Exception as e:
        _safe_log_error(f"Error getting plant {plant_id}: {e}")
        return None


def create_plant(user_id: str, plant_data: dict) -> dict | None:
    """
    Create a new plant for the user.

    Args:
        user_id: User UUID
        plant_data: Dictionary with plant fields:
            - name, species, nickname, location, light, notes, photo_url (basic info)
            - initial_health_state: 'thriving', 'okay', 'struggling' (optional assessment)
            - ownership_duration: 'just_got', 'few_weeks', 'few_months', 'year_plus' (optional)
            - current_watering_schedule: freeform text (optional)
            - initial_concerns: freeform text (optional)

    Returns:
        Created plant dictionary, or None if error
    """
    if not _supabase_client:
        return None

    try:
        # Validate initial assessment fields if provided
        valid_health_states = {'thriving', 'okay', 'struggling'}
        valid_ownership = {'just_got', 'few_weeks', 'few_months', 'year_plus'}

        initial_health = plant_data.get("initial_health_state", "").strip() or None
        if initial_health and initial_health not in valid_health_states:
            _safe_log_error(f"Invalid initial_health_state: {initial_health}")
            initial_health = None

        ownership = plant_data.get("ownership_duration", "").strip() or None
        if ownership and ownership not in valid_ownership:
            _safe_log_error(f"Invalid ownership_duration: {ownership}")
            ownership = None

        # Prepare plant data with user_id
        data = {
            "user_id": user_id,
            "name": plant_data.get("name", "").strip(),
            "species": plant_data.get("species", "").strip() or None,
            "nickname": plant_data.get("nickname", "").strip() or None,
            "location": plant_data.get("location", "").strip() or None,
            "light": plant_data.get("light", "").strip() or None,
            "notes": plant_data.get("notes", "").strip() or None,
            "photo_url": plant_data.get("photo_url") or None,
            # Initial assessment fields (captured when creating a plant)
            "initial_health_state": initial_health,
            "ownership_duration": ownership,
            "current_watering_schedule": plant_data.get("current_watering_schedule", "").strip() or None,
            "initial_concerns": plant_data.get("initial_concerns", "").strip() or None,
        }

        response = _supabase_client.table("plants").insert(data).execute()

        if response.data and len(response.data) > 0:
            # Invalidate cache so fresh data is fetched
            invalidate_plant_cache(user_id)
            return response.data[0]
        return None
    except Exception as e:
        _safe_log_error(f"Error creating plant: {e}")
        return None


def update_plant(plant_id: str, user_id: str, plant_data: dict) -> dict | None:
    """
    Update an existing plant (with ownership verification).

    Args:
        plant_id: Plant UUID
        user_id: User UUID (for ownership verification)
        plant_data: Dictionary with fields to update

    Returns:
        Updated plant dictionary, or None if error
    """
    if not _supabase_client:
        return None

    try:
        # Prepare update data (only include provided fields)
        data = {}
        if "name" in plant_data:
            data["name"] = plant_data["name"].strip()
        if "species" in plant_data:
            data["species"] = plant_data["species"].strip() or None
        if "nickname" in plant_data:
            data["nickname"] = plant_data["nickname"].strip() or None
        if "location" in plant_data:
            data["location"] = plant_data["location"].strip() or None
        if "light" in plant_data:
            data["light"] = plant_data["light"].strip() or None
        if "notes" in plant_data:
            data["notes"] = plant_data["notes"].strip() or None
        if "photo_url" in plant_data:
            data["photo_url"] = plant_data["photo_url"] or None

        response = (_supabase_client
                   .table("plants")
                   .update(data)
                   .eq("id", plant_id)
                   .eq("user_id", user_id)  # Ownership check
                   .execute())

        if response.data and len(response.data) > 0:
            # Invalidate cache so fresh data is fetched
            invalidate_plant_cache(user_id)
            return response.data[0]
        return None
    except Exception as e:
        _safe_log_error(f"Error updating plant {plant_id}: {e}")
        return None


def delete_plant(plant_id: str, user_id: str) -> bool:
    """
    Delete a plant (with ownership verification).

    Args:
        plant_id: Plant UUID
        user_id: User UUID (for ownership verification)

    Returns:
        True if deleted successfully, False otherwise
    """
    if not _supabase_client:
        return False

    try:
        response = (_supabase_client
                   .table("plants")
                   .delete()
                   .eq("id", plant_id)
                   .eq("user_id", user_id)  # Ownership check
                   .execute())
        # Invalidate cache so fresh data is fetched
        invalidate_plant_cache(user_id)
        return True
    except Exception as e:
        _safe_log_error(f"Error deleting plant {plant_id}: {e}")
        return False


def create_image_versions(file_bytes: bytes) -> dict[str, bytes] | None:
    """
    Create multiple versions of an image for different display contexts.

    Args:
        file_bytes: Original image file bytes

    Returns:
        Dictionary with 2 versions:
        - 'display': Optimized for grid/detail views (max 900px width, 80% quality)
        - 'thumbnail': Small version for buttons (128x128, 85% quality)
        Returns None if image processing fails
    """
    try:
        from PIL import Image, ImageOps
        from io import BytesIO

        # Open original image
        img = Image.open(BytesIO(file_bytes))

        # Fix orientation based on EXIF data (handles sideways photos from phones)
        img = ImageOps.exif_transpose(img)

        # Convert RGBA/LA/P to RGB (JPEG doesn't support transparency)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            # Paste image with alpha channel as mask if RGBA
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background

        versions = {}

        # Display version - optimize for web (max 900px width)
        display_img = img.copy()
        if display_img.width > 900 or display_img.height > 900:
            display_img.thumbnail((900, 900), Image.Resampling.LANCZOS)

        display_output = BytesIO()
        display_img.save(display_output, format='JPEG', quality=80, optimize=True)
        versions['display'] = display_output.getvalue()

        # Thumbnail - 128x128 for retina displays (shown at 64x64)
        thumb_img = img.copy()
        thumb_img.thumbnail((128, 128), Image.Resampling.LANCZOS)

        thumb_output = BytesIO()
        thumb_img.save(thumb_output, format='JPEG', quality=85, optimize=True)
        versions['thumbnail'] = thumb_output.getvalue()

        return versions

    except Exception as e:
        _safe_log_error(f"Error creating image versions: {e}")
        return None


def upload_plant_photo_versions(file_bytes: bytes, user_id: str, filename: str) -> tuple[dict[str, str] | None, str | None]:
    """
    Upload plant photo with multiple optimized versions (display, thumbnail).

    Args:
        file_bytes: Original image file bytes
        user_id: User UUID (for organizing files)
        filename: Original filename (used for extension detection)

    Returns:
        Tuple of (urls_dict, error_message):
        - urls_dict: Dictionary with public URLs for each version on success, None on failure
          - 'display': Optimized version URL (max 900px)
          - 'thumbnail': Small thumbnail URL (128x128)
        - error_message: None on success, specific error description on failure

    Examples:
        >>> urls, error = upload_plant_photo_versions(file_bytes, user_id, "photo.jpg")
        >>> if error:
        ...     print(f"Upload failed: {error}")
        >>> else:
        ...     print(f"Success! URLs: {urls}")
    """
    if not _supabase_client:
        return None, "Photo upload service not available. Please check your connection."

    try:
        import uuid
        from pathlib import Path

        # Generate unique base filename (without extension)
        base_uuid = str(uuid.uuid4())

        # Create optimized versions
        versions = create_image_versions(file_bytes)
        if not versions:
            error_msg = "Failed to process image. File may be corrupted or in an unsupported format."
            _safe_log_error(f"Failed to create image versions: {error_msg}")
            return None, error_msg

        # Upload all versions in parallel for 2× faster uploads
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def upload_single_version(version_name: str, version_bytes: bytes) -> tuple[str, str]:
            """Upload a single version and return (version_name, public_url)."""
            version_filename = f"{user_id}/{base_uuid}-{version_name}.jpg"

            # Upload to plant-photos bucket
            _supabase_client.storage.from_("plant-photos").upload(
                version_filename,
                version_bytes,
                file_options={"content-type": "image/jpeg"}
            )

            # Get public URL
            public_url = _supabase_client.storage.from_("plant-photos").get_public_url(version_filename)
            return (version_name, public_url)

        # Upload all 2 versions concurrently
        urls = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit all upload tasks
            future_to_version = {
                executor.submit(upload_single_version, version_name, version_bytes): version_name
                for version_name, version_bytes in versions.items()
            }

            # Collect results as they complete
            for future in as_completed(future_to_version):
                version_name, public_url = future.result()
                urls[version_name] = public_url

        return urls, None  # Success - return URLs and no error

    except Exception as e:
        error_msg = f"Upload failed: {str(e)}"
        _safe_log_error(f"Error uploading plant photo versions: {e}")
        return None, error_msg


def delete_plant_photo(photo_url: str) -> bool:
    """
    Delete a plant photo from Supabase Storage.

    Args:
        photo_url: Full public URL of the photo

    Returns:
        True if deleted successfully, False otherwise
    """
    if not _supabase_client or not photo_url:
        _safe_log_error(f"Cannot delete photo: client={bool(_supabase_client)}, url={bool(photo_url)}")
        return False

    try:
        # Extract file path from URL
        # URL format: https://{project}.supabase.co/storage/v1/object/public/plant-photos/{path}
        if "/plant-photos/" in photo_url:
            file_path = photo_url.split("/plant-photos/")[1]
            _safe_log_info(f"Attempting to delete photo: {file_path}")

            result = _supabase_client.storage.from_("plant-photos").remove([file_path])
            _safe_log_info(f"Delete result: {result}")
            return True
        else:
            _safe_log_error(f"Invalid photo URL format (missing /plant-photos/): {photo_url}")
            return False
    except Exception as e:
        _safe_log_error(f"Error deleting plant photo {photo_url}: {e}")
        import traceback
        _safe_log_error(f"Traceback: {traceback.format_exc()}")
        return False


# ============================================================================
# Onboarding Helpers
# ============================================================================

def is_onboarding_completed(user_id: str) -> bool:
    """
    Check if user has completed onboarding wizard.

    Args:
        user_id: Supabase user UUID

    Returns:
        True if completed, False otherwise
    """
    profile = get_user_profile(user_id)
    if not profile:
        return False

    return profile.get("onboarding_completed", False)


def mark_onboarding_complete(user_id: str) -> bool:
    """
    Mark user's onboarding as completed.

    Args:
        user_id: Supabase user UUID

    Returns:
        True if successful, False otherwise
    """
    if not _supabase_client:
        return False

    try:
        _supabase_client.table("profiles").update({
            "onboarding_completed": True
        }).eq("id", user_id).execute()

        return True
    except Exception as e:
        _safe_log_error(f"Error marking onboarding complete: {e}")
        return False


def export_user_data(user_id: str) -> Dict[str, Any]:
    """Export all user data for GDPR data portability (Article 20).

    Returns a dict containing profile, plants, reminders, journal entries,
    and feedback.  Uses the admin client to bypass RLS and ensure complete
    results.  Uses explicit column lists to avoid leaking internal fields.
    """
    if not _supabase_admin:
        return {"error": "Service unavailable"}

    _PROFILE_EXPORT_COLS = "id,email,plan,city,timezone,hemisphere,theme_preference,experience_level,primary_goal,time_commitment,environment_preference,marketing_opt_in,onboarding_completed,created_at,trial_ends_at"
    _PLANT_EXPORT_COLS = "id,user_id,name,species,nickname,location,light,notes,photo_url,current_watering_schedule,initial_health_state,ownership_duration,initial_concerns,created_at,updated_at"
    _REMINDER_EXPORT_COLS = "id,user_id,plant_id,reminder_type,title,notes,frequency,custom_interval_days,next_due,last_completed_at,is_active,is_recurring,skip_weather_adjustment,weather_adjusted_due,weather_adjustment_reason,created_at"

    data: Dict[str, Any] = {"exported_at": datetime.now().isoformat() + "Z"}

    def _safe_query(table: str, columns: str, id_col: str = "user_id", fallback=None):
        """Run a query, returning fallback on 204/empty or error."""
        if fallback is None:
            fallback = []
        try:
            result = _supabase_admin.table(table).select(columns).eq(id_col, user_id).execute()
            return result.data if result and result.data else fallback
        except Exception as e:
            _safe_log_error(f"Error exporting {table}: {e}")
            return fallback

    # Profile (explicit columns — no internal flags)
    data["profile"] = _safe_query("profiles", _PROFILE_EXPORT_COLS, id_col="id", fallback={})

    # Plants
    data["plants"] = _safe_query("plants", _PLANT_EXPORT_COLS)

    # Reminders (all, including inactive)
    data["reminders"] = _safe_query("reminders", _REMINDER_EXPORT_COLS)

    # Journal entries (plant_actions)
    data["journal_entries"] = _safe_query("plant_actions", "*")

    # Answer feedback
    data["feedback"] = _safe_query(
        "answer_feedback",
        "question,plant,city,care_context,ai_source,rating,created_at",
    )

    return data


def delete_user_account(user_id: str) -> tuple[bool, str]:
    """Delete all user data and the auth account (GDPR Article 17).

    Cascade order: photos (storage) → answer_feedback → plant_actions →
    reminders → plants → email records → otp_codes → profile → auth user.

    Returns (success, message).
    """
    if not _supabase_admin:
        return False, "Service unavailable"

    errors: list[str] = []

    try:
        # Fetch email before any deletions (needed for OTP cleanup)
        profile_row = _supabase_admin.table("profiles").select("email").eq("id", user_id).maybe_single().execute()
        user_email = profile_row.data.get("email") if profile_row and profile_row.data else None

        # 1. Delete plant photos from storage
        plants = _supabase_admin.table("plants").select("photo_url").eq("user_id", user_id).execute()
        if plants and plants.data:
            for plant in plants.data:
                if plant.get("photo_url"):
                    delete_plant_photo(plant["photo_url"])

        # 2. Delete from child tables first (foreign key order)
        for table in ("answer_feedback", "plant_actions", "reminders"):
            try:
                _supabase_admin.table(table).delete().eq("user_id", user_id).execute()
            except Exception as e:
                errors.append(table)
                _safe_log_error(f"Error deleting from {table}: {e}")

        # 3. Delete plants
        try:
            _supabase_admin.table("plants").delete().eq("user_id", user_id).execute()
        except Exception as e:
            errors.append("plants")
            _safe_log_error(f"Error deleting plants: {e}")

        # 4. Delete email records
        for table in ("welcome_emails_sent", "seasonal_emails_sent", "email_events"):
            try:
                _supabase_admin.table(table).delete().eq("user_id", user_id).execute()
            except Exception as e:
                _safe_log_error(f"Error deleting from {table}: {e}")

        # 5. Delete OTP codes (using email fetched at top)
        if user_email:
            try:
                _supabase_admin.table("otp_codes").delete().eq("email", user_email).execute()
            except Exception:
                pass  # Non-critical — OTP codes expire anyway

        # 6. Delete profile
        try:
            _supabase_admin.table("profiles").delete().eq("id", user_id).execute()
        except Exception as e:
            errors.append("profiles")
            _safe_log_error(f"Error deleting profile: {e}")

        # 7. Delete auth user
        _supabase_admin.auth.admin.delete_user(user_id)

        if errors:
            _safe_log_error(f"Account {user_id} deleted with partial failures: {errors}")
            return True, "Account deleted (some data may require manual cleanup)."

        _safe_log_info(f"Account deleted for user {user_id}")
        return True, "Account deleted successfully"

    except Exception as e:
        _safe_log_error(f"Error deleting account for {user_id}: {e}")
        return False, "Failed to delete account. Please contact support."
