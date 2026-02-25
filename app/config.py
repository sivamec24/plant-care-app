"""
Centralized configuration for all environments.

Select a config by setting:
  APP_CONFIG=app.config.DevConfig      # local dev
  APP_CONFIG=app.config.ProdConfig     # production (default if unset)
  APP_CONFIG=app.config.TestConfig     # pytest

Notes:
- SECRET_KEY is read from FLASK_SECRET_KEY
- Rate limiting uses Flask-Limiter v3 keys (RATELIMIT_*).
"""

from __future__ import annotations
import os
import secrets
from datetime import timedelta

class BaseConfig:
    # Secrets & basics — generate a random key if env var is missing so dev/test
    # never runs with an empty string (production enforces a real key at startup)
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
    DEBUG = False
    TESTING = False

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)  # Sessions last 7 days (security best practice)
    SESSION_COOKIE_SECURE = True  # Only send cookies over HTTPS (overridden in dev)
    SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access to cookies
    SESSION_COOKIE_SAMESITE = "Lax"  # CSRF protection (Lax allows normal links)

    # Feature flags
    UI_DEBUG_LINKS = os.getenv("UI_DEBUG_LINKS", "").strip().lower() in {"1", "true", "yes"}
    DEBUG_ENDPOINTS_ENABLED = os.getenv("DEBUG_ENDPOINTS_ENABLED", "false").lower() == "true"

    # Third-party keys
    OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # Supabase (Database + Auth + Storage)
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_REDIRECT_URL = os.getenv("SUPABASE_REDIRECT_URL", "http://localhost:5000/auth/callback")

    # Flask-Limiter v3
    RATELIMIT_ENABLED = os.getenv("RATELIMIT_ENABLED", "true").lower() == "true"
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "40 per minute; 2000 per day")
    RATELIMIT_ASK = os.getenv("RATELIMIT_ASK", "8 per minute; 1 per 2 seconds; 200 per day")

    # File uploads
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB max upload size

    # Plant limits
    FREE_TIER_PLANT_LIMIT = 20  # Maximum plants for free tier users

    # Rate limiting
    UPLOAD_RATE_LIMIT = "20 per hour"  # Rate limit for plant/journal photo uploads
    SIGNUP_RATE_LIMIT = "5 per minute; 20 per hour"  # Rate limit for signup attempts

    # AI Context Configuration
    AI_CONTEXT_DEFAULT_TIER = os.getenv("AI_CONTEXT_DEFAULT_TIER", "rich")  # "basic" or "rich"
    AI_CONTEXT_RICH_MAX_PLANTS = 10  # Max plants to include in rich context
    AI_CONTEXT_RICH_MAX_OBSERVATIONS = 3  # Max recent observations in rich context
    AI_CONTEXT_NOTES_TRUNCATE_LENGTH = 500  # Truncate plant notes to this length
    AI_CONTEXT_OBSERVATION_TRUNCATE_LENGTH = 100  # Truncate observation notes
    AI_CONTEXT_ENABLE_WEATHER = True  # Include weather-aware context
    AI_CONTEXT_ENABLE_PATTERNS = True  # Include care pattern analysis
    AI_CONTEXT_TOKEN_BUDGET_RICH = 800  # Target token count for rich context
    AI_CONTEXT_TOKEN_BUDGET_DIAGNOSTIC = 1200  # Target token count for diagnostic context

    # Watering Intelligence Configuration
    WATERING_INTELLIGENCE_ENABLED = os.getenv("WATERING_INTELLIGENCE_ENABLED", "true").lower() == "true"
    WATERING_ELIGIBILITY_MIN_HOURS = 48  # Minimum hours between waterings
    WATERING_STRESS_THRESHOLD_HOUSEPLANT = 2  # Stress score threshold for houseplants
    WATERING_STRESS_THRESHOLD_SHRUB = 2  # Stress score threshold for shrubs
    WATERING_STRESS_THRESHOLD_WILDFLOWER_GERMINATION = 2  # Weeks 1-3
    WATERING_STRESS_THRESHOLD_WILDFLOWER_ESTABLISHED = 3  # Week 4+
    WATERING_AUTO_ADJUST_REMINDERS = False  # Auto-adjust reminders based on weather (disabled)
    WATERING_RAIN_THRESHOLD_INCHES = 0.25  # Minimum rain to trigger skip
    WATERING_RAIN_SKIP_WINDOW_HOURS = 48  # Hours to skip after significant rain

    # Weather-Aware Reminder Configuration (Phase 2)
    WEATHER_REMINDER_ADJUSTMENTS_ENABLED = os.getenv("WEATHER_REMINDER_ADJUSTMENTS_ENABLED", "true").lower() == "true"
    WEATHER_ADJUSTMENT_RAIN_THRESHOLD_HEAVY = 0.5  # inches for automatic postponement
    WEATHER_ADJUSTMENT_RAIN_THRESHOLD_LIGHT = 0.25  # inches for suggestion
    WEATHER_ADJUSTMENT_FREEZE_THRESHOLD = 32  # °F for freeze warnings
    WEATHER_ADJUSTMENT_EXTREME_HEAT_THRESHOLD = 95  # °F for extreme heat warnings
    WEATHER_AI_INFERENCE_ENABLED = os.getenv("WEATHER_AI_INFERENCE_ENABLED", "true").lower() == "true"
    WEATHER_AI_INFERENCE_CACHE_HOURS = 168  # 1 week cache for AI plant inferences

    # Legal notification — bump this date when ToS/Privacy are materially changed
    # to re-show the in-app banner for all users.
    LEGAL_LAST_UPDATED = "2026-02-15"

    # Misc
    PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME", "https")
    SEND_FILE_MAX_AGE_DEFAULT = int(os.getenv("SEND_FILE_MAX_AGE_DEFAULT", "3600"))

class ProdConfig(BaseConfig):
    """Production settings (selected by default if APP_CONFIG is unset)."""
    pass

class DevConfig(BaseConfig):
    """Developer-friendly settings."""
    ENV = "development"
    DEBUG = True
    DEBUG_ENDPOINTS_ENABLED = True  # Enable debug endpoint in development
    TEMPLATES_AUTO_RELOAD = True
    # Disable aggressive static caching in dev
    SEND_FILE_MAX_AGE_DEFAULT = 0
    PREFERRED_URL_SCHEME = "http"
    # Allow cookies over HTTP in dev
    SESSION_COOKIE_SECURE = False
    # Relaxed rate limits for development/testing
    SIGNUP_RATE_LIMIT = "100 per minute; 500 per hour"  # Much higher for dev testing

class TestConfig(BaseConfig):
    """CI/pytest settings."""
    TESTING = True
    DEBUG = True
    # Usually disable the limiter in tests to avoid flakiness
    RATELIMIT_ENABLED = False
    # Fast templates/static in tests
    TEMPLATES_AUTO_RELOAD = True
    SEND_FILE_MAX_AGE_DEFAULT = 0