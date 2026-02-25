"""
Error handling utilities for sanitizing user-facing messages and logging.

Provides consistent error handling across the application:
- Sanitizes error messages to prevent information leakage
- Logs detailed error information for debugging
- Provides user-friendly error messages
"""

from __future__ import annotations
from typing import Tuple
from flask import current_app
import logging

# User-friendly generic error messages
GENERIC_MESSAGES = {
    "database": "We're experiencing technical difficulties. Please try again.",
    "validation": "The information provided is invalid. Please check and try again.",
    "upload": "Failed to upload file. Please try again.",
    "permission": "You don't have permission to perform this action.",
    "not_found": "The requested item was not found.",
    "network": "Network error occurred. Please check your connection and try again.",
}


def sanitize_error(
    error: Exception,
    error_type: str = "database",
    log_prefix: str = ""
) -> str:
    """
    Sanitize error message for user display and log full details.

    Security: Prevents exposing internal error messages, stack traces, or
    database schema information to end users. Full details are logged for debugging.

    Args:
        error: The exception that occurred
        error_type: Type of error (database, validation, upload, permission, not_found, network)
        log_prefix: Optional prefix for log message context

    Returns:
        User-friendly error message

    Examples:
        >>> try:
        ...     result = database_query()
        ... except Exception as e:
        ...     user_msg = sanitize_error(e, "database", "Failed to fetch plants")
        ...     flash(user_msg, "error")
    """
    # Log the full error details for debugging (not shown to user)
    error_message = str(error)
    log_message = f"{log_prefix}: {error_message}" if log_prefix else error_message

    # Use different log levels based on error type
    if error_type in ["validation", "not_found"]:
        # These are expected errors (user mistakes), log as info
        current_app.logger.info(f"Expected error - {log_message}")
    else:
        # Unexpected errors (bugs, system issues), log as error with stack trace
        current_app.logger.error(f"Unexpected error - {log_message}", exc_info=True)

    # Return sanitized user-friendly message
    return GENERIC_MESSAGES.get(error_type, GENERIC_MESSAGES["database"])


def handle_service_error(
    result: Tuple[any, str | None],
    success_data_index: int = 0
) -> Tuple[any, str]:
    """
    Handle service layer errors consistently.

    Service functions typically return (data, error_message) tuples.
    This helper sanitizes and logs errors while preserving successful results.

    Args:
        result: Tuple of (data, error_message) from service function
        success_data_index: Index of success data in tuple (usually 0)

    Returns:
        Tuple of (data, sanitized_error_or_none)

    Examples:
        >>> plant, error = supabase_client.create_plant(user_id, plant_data)
        >>> plant, error = handle_service_error((plant, error))
        >>> if error:
        ...     flash(error, "error")
    """
    data = result[success_data_index]
    error = result[1] if len(result) > 1 else None

    if error:
        # Log original error, return sanitized message
        current_app.logger.error(f"Service error: {error}")
        return data, GENERIC_MESSAGES["database"]

    return data, None


def log_warning(message: str, **context) -> None:
    """
    Log a warning with optional context.

    Args:
        message: Warning message
        **context: Additional context key-value pairs

    Examples:
        >>> log_warning("Rate limit exceeded", user_id="123", endpoint="/api/plants")
    """
    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        message = f"{message} | Context: {context_str}"

    current_app.logger.warning(message)


def log_info(message: str, **context) -> None:
    """
    Log an info message with optional context.

    Args:
        message: Info message
        **context: Additional context key-value pairs

    Examples:
        >>> log_info("Plant created", user_id="123", plant_name="Monstera")
    """
    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        message = f"{message} | Context: {context_str}"

    current_app.logger.info(message)
