"""
Simple caching utilities for performance optimization.

Provides time-based caching for expensive operations like database queries.
"""

from __future__ import annotations
from cachetools import TTLCache
from typing import Callable, Any, Hashable
from functools import wraps
import threading

# Cache configuration constants
CALENDAR_CACHE_TTL_SECONDS = 300  # 5 minutes
CALENDAR_CACHE_MAX_ENTRIES = 1000

# Thread-safe calendar cache (5-minute TTL, max 1000 entries)
# Key format: "calendar:{user_id}:{year}:{month}"
_calendar_cache = TTLCache(maxsize=CALENDAR_CACHE_MAX_ENTRIES, ttl=CALENDAR_CACHE_TTL_SECONDS)
_cache_lock = threading.Lock()


def cache_calendar_data(func: Callable) -> Callable:
    """
    Decorator to cache calendar reminder data for 5 minutes.

    Cache key includes user_id, year, and month to ensure proper isolation.
    Thread-safe using lock to prevent race conditions.

    Usage:
        @cache_calendar_data
        def get_reminders_for_month(user_id, year, month):
            # Expensive database query...
            return reminders
    """
    @wraps(func)
    def wrapper(user_id: str, year: int, month: int) -> Any:
        # Create unique cache key
        cache_key = f"calendar:{user_id}:{year}:{month}"

        # Try to get from cache (thread-safe)
        with _cache_lock:
            if cache_key in _calendar_cache:
                return _calendar_cache[cache_key]

        # Not in cache - call the function
        result = func(user_id, year, month)

        # Store in cache (thread-safe)
        with _cache_lock:
            _calendar_cache[cache_key] = result

        return result

    return wrapper


def invalidate_user_calendar_cache(user_id: str) -> None:
    """
    Invalidate all calendar cache entries for a specific user.

    Called when:
    - User creates a new reminder
    - User updates an existing reminder
    - User deletes a reminder
    - User completes a reminder (changes next_due)

    Args:
        user_id: UUID of the user whose cache should be cleared
    """
    with _cache_lock:
        # Find and remove all keys for this user
        keys_to_remove = [
            key for key in _calendar_cache.keys()
            if key.startswith(f"calendar:{user_id}:")
        ]
        for key in keys_to_remove:
            del _calendar_cache[key]


def clear_all_calendar_cache() -> None:
    """
    Clear the entire calendar cache.

    Useful for:
    - Testing
    - Manual cache invalidation
    - System maintenance
    """
    with _cache_lock:
        _calendar_cache.clear()
