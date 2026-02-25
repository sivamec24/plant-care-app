"""
Marketing email service for welcome series and subscriber management.

Provides:
- Automated welcome email series (Day 0, Day 3, Day 7)
- Duplicate prevention via welcome_emails_sent table
- Resend Audience sync for campaign management
- Unsubscribe token generation
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from html import escape as html_escape
from typing import Dict, Any, List, Optional
import os
import requests
from flask import current_app, has_app_context
from itsdangerous import URLSafeSerializer
from app.utils.sanitize import mask_email as _mask_email


# Email type constants
WELCOME_DAY_0 = "welcome_day0"
WELCOME_DAY_3 = "welcome_day3"
WELCOME_DAY_7 = "welcome_day7"
WELCOME_DAY_10 = "welcome_day10"
REENGAGEMENT_14DAY = "reengagement_14day"

# Seasonal email constants
SEASONAL_SPRING = "seasonal_spring"
SEASONAL_SUMMER = "seasonal_summer"
SEASONAL_FALL = "seasonal_fall"
SEASONAL_WINTER = "seasonal_winter"

# Milestone email constants
MILESTONE_FIRST_PLANT = "milestone_first_plant"
MILESTONE_ANNIVERSARY_30 = "milestone_anniversary_30"
MILESTONE_STREAK_5 = "milestone_streak_5"
MILESTONE_COLLECTION_5 = "milestone_collection_5"


def _is_marketing_enabled() -> bool:
    """Check if marketing emails are enabled via environment variable."""
    return os.getenv("MARKETING_EMAILS_ENABLED", "").lower() in ("true", "1", "yes")


def _safe_log_error(message: str) -> None:
    """Log error message only if Flask app context is available."""
    try:
        if has_app_context():
            current_app.logger.error(message)
    except (ImportError, RuntimeError):
        pass


def _safe_log_info(message: str) -> None:
    """Log info message only if Flask app context is available."""
    try:
        if has_app_context():
            current_app.logger.info(message)
    except (ImportError, RuntimeError):
        pass


def get_unsubscribe_url(user_id: str) -> str:
    """
    Generate a signed unsubscribe URL for the user.

    Args:
        user_id: User's UUID

    Returns:
        Full unsubscribe URL with signed token
    """
    try:
        secret_key = current_app.secret_key or os.getenv("SECRET_KEY", "dev-secret")
        s = URLSafeSerializer(secret_key, salt="unsubscribe")
        token = s.dumps(user_id)

        # Build URL manually to work outside request context (scheduler jobs)
        # url_for with _external=True requires SERVER_NAME or active request
        base_url = os.getenv("APP_URL", "https://plantcareai.app")
        return f"{base_url}/unsubscribe/{token}"
    except Exception as e:
        _safe_log_error(f"Error generating unsubscribe URL: {e}")
        # Fallback to account settings page
        base_url = os.getenv("APP_URL", "https://plantcareai.app")
        return f"{base_url}/dashboard/account"


def verify_unsubscribe_token(token: str) -> Optional[str]:
    """
    Verify an unsubscribe token and return the user_id.

    Args:
        token: Signed token from unsubscribe URL

    Returns:
        user_id if valid, None if invalid/expired
    """
    try:
        secret_key = current_app.secret_key or os.getenv("SECRET_KEY", "dev-secret")
        s = URLSafeSerializer(secret_key, salt="unsubscribe")
        user_id = s.loads(token, max_age=30 * 24 * 60 * 60)  # Valid for 30 days
        return user_id
    except Exception as e:
        _safe_log_error(f"Invalid unsubscribe token: {e}")
        return None


def _send_via_resend(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    unsubscribe_url: str
) -> Dict[str, Any]:
    """
    Send an email via Resend API with standard marketing email headers.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_content: HTML email body
        text_content: Plain text email body
        unsubscribe_url: Unsubscribe URL for headers

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        _safe_log_error("RESEND_API_KEY not configured")
        return {"success": False, "error": "email_not_configured"}

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": "Ellen from PlantCareAI <hello@updates.plantcareai.app>",
                "to": [to_email],
                "reply_to": "support@plantcareai.app",
                "subject": subject,
                "html": html_content,
                "text": text_content,
                "headers": {
                    "List-Unsubscribe": f"<{unsubscribe_url}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                },
                "tracking": {
                    "click": False,
                    "open": False,
                },
            },
            timeout=10,
        )

        if response.status_code == 200:
            return {"success": True, "message": "sent"}
        else:
            error_data = response.json() if response.text else {}
            error_message = error_data.get("message", "Unknown error")
            _safe_log_error(f"Resend API error: {response.status_code} - {error_message}")
            return {"success": False, "error": "email_send_failed"}

    except requests.exceptions.Timeout:
        _safe_log_error("Resend API timeout")
        return {"success": False, "error": "timeout"}
    except Exception as e:
        _safe_log_error(f"Error sending email via Resend: {e}")
        return {"success": False, "error": str(e)}


def _get_email_footer(unsubscribe_url: str) -> str:
    """Generate the email footer with unsubscribe link."""
    return f"""
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #faf8f6; padding: 24px 40px; border-top: 1px solid #e8e3dd;">
                            <p style="margin: 0 0 8px; color: #78716c; font-size: 12px; text-align: center;">
                                You received this because you signed up for PlantCareAI updates.
                            </p>
                            <p style="margin: 0; color: #a69d91; font-size: 11px; text-align: center;">
                                <a href="{unsubscribe_url}" style="color: #a69d91; text-decoration: underline;">Unsubscribe</a>
                                from marketing emails
                            </p>
                        </td>
                    </tr>
"""


def _get_welcome_day0_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate Day 0 welcome email (immediate)."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to PlantCareAI!</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">🌱</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 600;">Welcome to PlantCareAI!</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <h2 style="margin: 0 0 16px; color: #111827; font-size: 20px; font-weight: 600;">You're all set to grow! 🎉</h2>
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Thanks for joining PlantCareAI. We're here to help your plants thrive with smart care reminders and AI-powered advice.
                            </p>

                            <h3 style="margin: 24px 0 16px; color: #111827; font-size: 18px; font-weight: 600;">Quick Start Guide</h3>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #ecfdf5; border-radius: 8px; margin-bottom: 12px;">
                                        <p style="margin: 0; color: #065f46; font-size: 14px;">
                                            <strong>1. Add your plants</strong><br>
                                            Snap a photo and tell us what you're growing. We'll help track care schedules.
                                        </p>
                                    </td>
                                </tr>
                                <tr><td style="height: 12px;"></td></tr>
                                <tr>
                                    <td style="padding: 16px; background-color: #f0f9ff; border-radius: 8px; margin-bottom: 12px;">
                                        <p style="margin: 0; color: #1e40af; font-size: 14px;">
                                            <strong>2. Set reminders</strong><br>
                                            Get notified when it's time to water, fertilize, or rotate your plants.
                                        </p>
                                    </td>
                                </tr>
                                <tr><td style="height: 12px;"></td></tr>
                                <tr>
                                    <td style="padding: 16px; background-color: #fef3c7; border-radius: 8px;">
                                        <p style="margin: 0; color: #92400e; font-size: 14px;">
                                            <strong>3. Ask our AI</strong><br>
                                            Got questions? Our plant care AI knows all about watering, light, and troubleshooting.
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Happy growing! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>

{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """Welcome to PlantCareAI! 🌱

You're all set to grow!

Thanks for joining PlantCareAI. We're here to help your plants thrive with smart care reminders and AI-powered advice.

QUICK START GUIDE:

1. Add your plants
Snap a photo and tell us what you're growing. We'll help track care schedules.

2. Set reminders
Get notified when it's time to water, fertilize, or rotate your plants.

3. Ask our AI
Got questions? Our plant care AI knows all about watering, light, and troubleshooting.

Happy growing! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "Welcome to PlantCareAI! 🌱 Let's grow together",
        "html": html_content,
        "text": text_content
    }


def _get_welcome_day3_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate Day 3 welcome email (plant care tips)."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Plant Care Tips from PlantCareAI</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">💧</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">3 Tips for Happy Plants</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Here are some expert tips to help your plants flourish:
                            </p>

                            <h3 style="margin: 0 0 12px; color: #111827; font-size: 18px; font-weight: 600;">🌊 Tip #1: Check the soil, not the calendar</h3>
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                Instead of watering on a fixed schedule, stick your finger 1-2 inches into the soil. If it's dry, water thoroughly. If moist, wait another day or two. Most houseplant problems come from overwatering!
                            </p>

                            <h3 style="margin: 0 0 12px; color: #111827; font-size: 18px; font-weight: 600;">☀️ Tip #2: Light matters more than you think</h3>
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                "Bright indirect light" means near a window but not in direct sun rays. North-facing windows = low light. South-facing = bright. East/West = medium. Match your plants to their light needs!
                            </p>

                            <h3 style="margin: 0 0 12px; color: #111827; font-size: 18px; font-weight: 600;">🔄 Tip #3: Rotate for even growth</h3>
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                Give your plants a quarter turn every time you water. This helps them grow evenly instead of leaning toward the light. Your future self will thank you!
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 24px 0;">
                                <tr>
                                    <td style="background-color: #ecfdf5; border-radius: 8px; padding: 20px; text-align: center;">
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px; font-weight: 600;">
                                            💡 Pro tip: Use our AI assistant for personalized advice
                                        </p>
                                        <p style="margin: 0; color: #047857; font-size: 13px;">
                                            Just ask about your specific plant and we'll help!
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Keep growing! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>

{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """3 Tips for Happy Plants 💧

Here are some expert tips to help your plants flourish:

TIP #1: Check the soil, not the calendar 🌊
Instead of watering on a fixed schedule, stick your finger 1-2 inches into the soil. If it's dry, water thoroughly. If moist, wait another day or two. Most houseplant problems come from overwatering!

TIP #2: Light matters more than you think ☀️
"Bright indirect light" means near a window but not in direct sun rays. North-facing windows = low light. South-facing = bright. East/West = medium. Match your plants to their light needs!

TIP #3: Rotate for even growth 🔄
Give your plants a quarter turn every time you water. This helps them grow evenly instead of leaning toward the light. Your future self will thank you!

💡 Pro tip: Use our AI assistant for personalized advice about your specific plants!

Keep growing! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "💧 3 simple tips for happier plants",
        "html": html_content,
        "text": text_content
    }


def _get_welcome_day7_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate Day 7 welcome email (weather feature deep dive)."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Plants Check the Weather Now</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">🌦️</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Your Plants Check the Weather Now</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Here's something most people don't realize about PlantCareAI: <strong>it adjusts your reminders based on weather.</strong>
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 20px; background-color: #dbeafe; border-radius: 8px;">
                                        <h3 style="margin: 0 0 8px; color: #1e40af; font-size: 16px; font-weight: 600;">☔ Rain expected tomorrow?</h3>
                                        <p style="margin: 0; color: #1e40af; font-size: 14px; line-height: 1.5;">
                                            Outdoor watering reminders get postponed automatically. No more overwatering!
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 20px; background-color: #fef3c7; border-radius: 8px;">
                                        <h3 style="margin: 0 0 8px; color: #92400e; font-size: 16px; font-weight: 600;">🥶 Frost warning?</h3>
                                        <p style="margin: 0; color: #92400e; font-size: 14px; line-height: 1.5;">
                                            You'll get a heads up to move sensitive plants indoors or cover them up.
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 20px; background-color: #fee2e2; border-radius: 8px;">
                                        <h3 style="margin: 0 0 8px; color: #991b1b; font-size: 16px; font-weight: 600;">🔥 Heatwave coming?</h3>
                                        <p style="margin: 0; color: #991b1b; font-size: 14px; line-height: 1.5;">
                                            We'll suggest extra watering and shade for plants that need it.
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0 0 16px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                This happens automatically — you don't have to do anything. Just make sure your location is set in settings.
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="background-color: #ecfdf5; border-radius: 8px; padding: 20px; text-align: center;">
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px; font-weight: 600;">
                                            💡 Not getting weather adjustments?
                                        </p>
                                        <p style="margin: 0; color: #047857; font-size: 13px;">
                                            Make sure location permissions are enabled, or set your city manually in settings.
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0 0 24px; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Honestly, this single feature has saved me from overwatering more times than I can count. Turns out plants don't need water when it's about to rain. Who knew? (The AI knew.)
                            </p>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Happy growing! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>

{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """Your Plants Check the Weather Now 🌦️

Here's something most people don't realize about PlantCareAI: it adjusts your reminders based on weather.

☔ RAIN EXPECTED TOMORROW?
Outdoor watering reminders get postponed automatically. No more overwatering!

🥶 FROST WARNING?
You'll get a heads up to move sensitive plants indoors or cover them up.

🔥 HEATWAVE COMING?
We'll suggest extra watering and shade for plants that need it.

This happens automatically — you don't have to do anything. Just make sure your location is set in settings.

💡 Not getting weather adjustments? Make sure location permissions are enabled, or set your city manually in settings.

Honestly, this single feature has saved me from overwatering more times than I can count. Turns out plants don't need water when it's about to rain. Who knew? (The AI knew.)

Happy growing! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "🌦️ Your plants check the weather now",
        "html": html_content,
        "text": text_content
    }


def _get_welcome_day10_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate Day 10 welcome email (journaling deep dive)."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Best Way to Improve at Plant Care</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">📔</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">The Best Way to Improve at Plant Care</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Want to know the #1 way to get better at plant care? <strong>Track what you do.</strong>
                            </p>

                            <p style="margin: 0 0 16px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                I know, I know — it sounds tedious. But here's why it matters:
                            </p>

                            <p style="margin: 0 0 24px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                After a few months of logging, you'll know:
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #f4f1ed; border-radius: 8px;">
                                        <p style="margin: 0 0 12px; color: #44403c; font-size: 14px; line-height: 1.6;">
                                            ✓ How often your monstera <em>actually</em> needs water (not what Google says)
                                        </p>
                                        <p style="margin: 0 0 12px; color: #44403c; font-size: 14px; line-height: 1.6;">
                                            ✓ When you fertilized last (was it 2 weeks ago or 2 months?)
                                        </p>
                                        <p style="margin: 0 0 12px; color: #44403c; font-size: 14px; line-height: 1.6;">
                                            ✓ What worked when your plant was struggling
                                        </p>
                                        <p style="margin: 0; color: #44403c; font-size: 14px; line-height: 1.6;">
                                            ✓ How much it's grown (photos don't lie!)
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <h3 style="margin: 0 0 16px; color: #111827; font-size: 18px; font-weight: 600;">PlantCareAI's journal makes this easy:</h3>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #ecfdf5; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px;">
                                            <strong>💧 One tap to log</strong> watering, fertilizing, repotting
                                        </p>
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px;">
                                            <strong>📸 Add photos</strong> to see progress over time
                                        </p>
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px;">
                                            <strong>📝 Notes</strong> for anything else ("moved to brighter spot")
                                        </p>
                                        <p style="margin: 0; color: #065f46; font-size: 14px;">
                                            <strong>📊 Timeline view</strong> to spot patterns
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="background-color: #fef3c7; border-radius: 8px; padding: 20px; text-align: center;">
                                        <p style="margin: 0; color: #92400e; font-size: 14px;">
                                            💡 You don't need to log everything. Even just tracking waterings is a game-changer.
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Happy growing! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>

{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """The Best Way to Improve at Plant Care 📔

Want to know the #1 way to get better at plant care? Track what you do.

I know, I know — it sounds tedious. But here's why it matters:

After a few months of logging, you'll know:
✓ How often your monstera actually needs water (not what Google says)
✓ When you fertilized last (was it 2 weeks ago or 2 months?)
✓ What worked when your plant was struggling
✓ How much it's grown (photos don't lie!)

PLANTCAREAI'S JOURNAL MAKES THIS EASY:

💧 One tap to log watering, fertilizing, repotting
📸 Add photos to see progress over time
📝 Notes for anything else ("moved to brighter spot")
📊 Timeline view to spot patterns

💡 You don't need to log everything. Even just tracking waterings is a game-changer.

Happy growing! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "📔 The best way to improve at plant care",
        "html": html_content,
        "text": text_content
    }


def _get_reengagement_14day_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate re-engagement email for users inactive 14+ days."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Plants Miss You</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">🌿</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Your Plants Miss You</h1>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Hey! It's been a little while since we've seen you.
                            </p>

                            <p style="margin: 0 0 24px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                Whether you've been busy, traveling, or just taking a break from screens — we get it. But your plants are still growing, and we're here to help whenever you're ready!
                            </p>

                            <h3 style="margin: 0 0 16px; color: #111827; font-size: 18px; font-weight: 600;">Here's what you can do in 30 seconds:</h3>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #ecfdf5; border-radius: 8px;">
                                        <p style="margin: 0 0 12px; color: #065f46; font-size: 14px; line-height: 1.6;">
                                            ✓ <strong>Check your reminders</strong> — any waterings overdue?
                                        </p>
                                        <p style="margin: 0 0 12px; color: #065f46; font-size: 14px; line-height: 1.6;">
                                            ✓ <strong>Add a new plant</strong> — got any new additions?
                                        </p>
                                        <p style="margin: 0; color: #065f46; font-size: 14px; line-height: 1.6;">
                                            ✓ <strong>Ask the AI</strong> — noticed any plant problems lately?
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="background-color: #fef3c7; border-radius: 8px; padding: 20px; text-align: center;">
                                        <p style="margin: 0; color: #92400e; font-size: 14px;">
                                            💡 <strong>Tip:</strong> Even a quick check-in once a week can make a big difference for your plants!
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Happy growing! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>

{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """Your Plants Miss You 🌿

Hey! It's been a little while since we've seen you.

Whether you've been busy, traveling, or just taking a break from screens — we get it. But your plants are still growing, and we're here to help whenever you're ready!

HERE'S WHAT YOU CAN DO IN 30 SECONDS:

✓ Check your reminders — any waterings overdue?
✓ Add a new plant — got any new additions?
✓ Ask the AI — noticed any plant problems lately?

💡 Tip: Even a quick check-in once a week can make a big difference for your plants!

Happy growing! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "🌿 Your plants miss you",
        "html": html_content,
        "text": text_content
    }


def _get_seasonal_spring_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate spring seasonal email (March)."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spring Plant Care Checklist</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">🌸</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Spring Checklist for Your Plants</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Spring is here! Your plants are waking up from their winter rest, and now's the perfect time to give them some extra love.
                            </p>

                            <h3 style="margin: 0 0 16px; color: #111827; font-size: 18px; font-weight: 600;">Your Spring To-Do List:</h3>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #ecfdf5; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px;"><strong>🌱 Start fertilizing again</strong></p>
                                        <p style="margin: 0; color: #065f46; font-size: 13px;">Your plants are hungry after winter dormancy. Resume your regular fertilizing schedule.</p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #fef3c7; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #92400e; font-size: 14px;"><strong>🪴 Check if anyone needs repotting</strong></p>
                                        <p style="margin: 0; color: #92400e; font-size: 13px;">Roots coming out the bottom? Plant wobbly? Time for a bigger pot!</p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #dbeafe; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #1e40af; font-size: 14px;"><strong>✂️ Propagate your favorites</strong></p>
                                        <p style="margin: 0; color: #1e40af; font-size: 13px;">Spring is prime propagation season. Take cuttings to grow your collection!</p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Happy spring! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>
{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """Spring Checklist for Your Plants 🌸

Spring is here! Your plants are waking up from their winter rest, and now's the perfect time to give them some extra love.

YOUR SPRING TO-DO LIST:

🌱 Start fertilizing again
Your plants are hungry after winter dormancy. Resume your regular fertilizing schedule.

🪴 Check if anyone needs repotting
Roots coming out the bottom? Plant wobbly? Time for a bigger pot!

✂️ Propagate your favorites
Spring is prime propagation season. Take cuttings to grow your collection!

Happy spring! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "🌸 Spring checklist for your plants",
        "html": html_content,
        "text": text_content
    }


def _get_seasonal_summer_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate summer seasonal email (June)."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Summer Plant Care Tips</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="background: linear-gradient(135deg, #f59e0b 0%, #ef4444 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">☀️</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Summer Care Tips</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Summer heat is here! Here's how to keep your plants happy when temperatures rise.
                            </p>

                            <h3 style="margin: 0 0 16px; color: #111827; font-size: 18px; font-weight: 600;">Beat the Heat:</h3>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #dbeafe; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #1e40af; font-size: 14px;"><strong>💧 Water more often</strong></p>
                                        <p style="margin: 0; color: #1e40af; font-size: 13px;">Plants drink more in hot weather. Check soil moisture daily during heat waves.</p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #fef3c7; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #92400e; font-size: 14px;"><strong>🌤️ Watch for sunburn</strong></p>
                                        <p style="margin: 0; color: #92400e; font-size: 13px;">Move sensitive plants away from intense afternoon sun. Sheer curtains help!</p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #ecfdf5; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px;"><strong>🌬️ Boost humidity</strong></p>
                                        <p style="margin: 0; color: #065f46; font-size: 13px;">AC can dry out the air. Group plants together or use a pebble tray for extra humidity.</p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Stay cool! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>
{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """Summer Care Tips ☀️

Summer heat is here! Here's how to keep your plants happy when temperatures rise.

BEAT THE HEAT:

💧 Water more often
Plants drink more in hot weather. Check soil moisture daily during heat waves.

🌤️ Watch for sunburn
Move sensitive plants away from intense afternoon sun. Sheer curtains help!

🌬️ Boost humidity
AC can dry out the air. Group plants together or use a pebble tray for extra humidity.

Stay cool! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "☀️ Summer care tips for your plants",
        "html": html_content,
        "text": text_content
    }


def _get_seasonal_fall_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate fall seasonal email (September)."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Preparing Your Plants for Fall</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="background: linear-gradient(135deg, #f59e0b 0%, #dc2626 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">🍂</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Preparing Plants for Fall</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                As days get shorter and cooler, your plants are starting to slow down. Here's how to help them transition.
                            </p>

                            <h3 style="margin: 0 0 16px; color: #111827; font-size: 18px; font-weight: 600;">Fall Prep Checklist:</h3>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #fef3c7; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #92400e; font-size: 14px;"><strong>🏠 Bring outdoor plants inside</strong></p>
                                        <p style="margin: 0; color: #92400e; font-size: 13px;">Before first frost! Check for pests before bringing them indoors.</p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #dbeafe; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #1e40af; font-size: 14px;"><strong>💧 Reduce watering</strong></p>
                                        <p style="margin: 0; color: #1e40af; font-size: 13px;">Growth slows in fall. Let soil dry out more between waterings.</p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #ecfdf5; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px;"><strong>☀️ Maximize light</strong></p>
                                        <p style="margin: 0; color: #065f46; font-size: 13px;">Move plants closer to windows as daylight decreases. Clean dusty leaves!</p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Happy fall! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>
{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """Preparing Plants for Fall 🍂

As days get shorter and cooler, your plants are starting to slow down. Here's how to help them transition.

FALL PREP CHECKLIST:

🏠 Bring outdoor plants inside
Before first frost! Check for pests before bringing them indoors.

💧 Reduce watering
Growth slows in fall. Let soil dry out more between waterings.

☀️ Maximize light
Move plants closer to windows as daylight decreases. Clean dusty leaves!

Happy fall! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "🍂 Preparing your plants for fall",
        "html": html_content,
        "text": text_content
    }


def _get_seasonal_winter_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate winter seasonal email (November)."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Winter Dormancy Tips</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="background: linear-gradient(135deg, #6366f1 0%, #3b82f6 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">❄️</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Winter Dormancy Tips</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Winter is here, and your plants are taking a well-deserved rest. Here's how to care for them during their dormant period.
                            </p>

                            <h3 style="margin: 0 0 16px; color: #111827; font-size: 18px; font-weight: 600;">Winter Care Basics:</h3>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #dbeafe; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #1e40af; font-size: 14px;"><strong>💧 Water less often</strong></p>
                                        <p style="margin: 0; color: #1e40af; font-size: 13px;">Most plants need significantly less water in winter. Overwatering is the #1 winter killer!</p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 16px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #fef3c7; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #92400e; font-size: 14px;"><strong>🚫 Stop fertilizing</strong></p>
                                        <p style="margin: 0; color: #92400e; font-size: 13px;">Plants don't need food when they're not actively growing. Resume in spring!</p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #ecfdf5; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px;"><strong>🌡️ Watch for drafts</strong></p>
                                        <p style="margin: 0; color: #065f46; font-size: 13px;">Keep plants away from cold windows, doors, and heating vents.</p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Stay cozy! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>
{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """Winter Dormancy Tips ❄️

Winter is here, and your plants are taking a well-deserved rest. Here's how to care for them during their dormant period.

WINTER CARE BASICS:

💧 Water less often
Most plants need significantly less water in winter. Overwatering is the #1 winter killer!

🚫 Stop fertilizing
Plants don't need food when they're not actively growing. Resume in spring!

🌡️ Watch for drafts
Keep plants away from cold windows, doors, and heating vents.

Stay cozy! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "❄️ Winter dormancy tips for your plants",
        "html": html_content,
        "text": text_content
    }


def _get_milestone_first_plant_email(unsubscribe_url: str) -> Dict[str, str]:
    """Generate milestone email for first plant added."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your First Plant Is In!</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">🌱</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Your First Plant Is In!</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                You just added your first plant to PlantCareAI. This is where the magic starts!
                            </p>

                            <p style="margin: 0 0 16px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                Here's what happens next:
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #ecfdf5; border-radius: 8px;">
                                        <p style="margin: 0 0 12px; color: #065f46; font-size: 14px; line-height: 1.6;">
                                            ✓ We'll remind you when it's time to water
                                        </p>
                                        <p style="margin: 0 0 12px; color: #065f46; font-size: 14px; line-height: 1.6;">
                                            ✓ Track your plant's growth over time
                                        </p>
                                        <p style="margin: 0; color: #065f46; font-size: 14px; line-height: 1.6;">
                                            ✓ Get personalized care tips from our AI
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="background-color: #fef3c7; border-radius: 8px; padding: 20px; text-align: center;">
                                        <p style="margin: 0; color: #92400e; font-size: 14px;">
                                            💡 <strong>Pro tip:</strong> Add a photo to your plant profile — you'll love looking back at it months from now!
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Happy growing! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>
{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = """Your First Plant Is In! 🌱

You just added your first plant to PlantCareAI. This is where the magic starts!

Here's what happens next:
✓ We'll remind you when it's time to water
✓ Track your plant's growth over time
✓ Get personalized care tips from our AI

💡 Pro tip: Add a photo to your plant profile — you'll love looking back at it months from now!

Happy growing! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "🌱 Your first plant is in!",
        "html": html_content,
        "text": text_content
    }


def _get_milestone_anniversary_30_email(unsubscribe_url: str, plant_name: str) -> Dict[str, str]:
    """Generate milestone email for 30-day plant anniversary."""
    # Escape plant_name to prevent XSS in HTML email
    safe_plant_name = html_escape(plant_name)
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>One Month Together!</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="background: linear-gradient(135deg, #f59e0b 0%, #ef4444 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">🎂</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">One Month Together!</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                Your <strong>{safe_plant_name}</strong> has been with you for 1 month now! <span aria-label="party">🎉</span>
                            </p>

                            <p style="margin: 0 0 24px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                That's 30 days of learning what makes your plant happy. You've probably figured out its favorite spot, how thirsty it gets, and maybe even started to notice new growth.
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 20px; background-color: #ecfdf5; border-radius: 8px; text-align: center;">
                                        <p style="margin: 0 0 8px; color: #065f46; font-size: 14px; font-weight: 600;">
                                            📸 Snap a photo today!
                                        </p>
                                        <p style="margin: 0; color: #047857; font-size: 13px;">
                                            Monthly photos are the best way to see how much your plant grows over time.
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Here's to many more months together! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>
{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = f"""One Month Together! 🎂

Your {plant_name} has been with you for 1 month now! 🎉

That's 30 days of learning what makes your plant happy. You've probably figured out its favorite spot, how thirsty it gets, and maybe even started to notice new growth.

📸 Snap a photo today!
Monthly photos are the best way to see how much your plant grows over time.

Here's to many more months together! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": f"🎂 {safe_plant_name} has been with you for 1 month!",
        "html": html_content,
        "text": text_content
    }


def _get_milestone_streak_5_email(unsubscribe_url: str, streak_count: int) -> Dict[str, str]:
    """Generate milestone email for watering streak."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>You're on a Streak!</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="background: linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">💧</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">You're on a {streak_count}-Day Streak!</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                You've logged plant care for <strong>{streak_count} days in a row!</strong> Your plants are lucky to have you.
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 24px; background-color: #dbeafe; border-radius: 8px; text-align: center;">
                                        <p style="margin: 0; color: #1e40af; font-size: 36px; font-weight: bold;">
                                            {streak_count} 🔥
                                        </p>
                                        <p style="margin: 8px 0 0; color: #1e40af; font-size: 14px;">
                                            days of consistent care
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0 0 24px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                Consistency is the secret to happy plants. Keep it up and watch your garden thrive!
                            </p>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Keep growing! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>
{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = f"""You're on a {streak_count}-Day Streak! 💧

You've logged plant care for {streak_count} days in a row! Your plants are lucky to have you.

{streak_count} 🔥 days of consistent care

Consistency is the secret to happy plants. Keep it up and watch your garden thrive!

Keep growing! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": f"💧 You're on a {streak_count}-day streak!",
        "html": html_content,
        "text": text_content
    }


def _get_milestone_collection_5_email(unsubscribe_url: str, plant_count: int) -> Dict[str, str]:
    """Generate milestone email for growing collection."""
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Collection Is Growing!</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f4f1ed;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f1ed; padding: 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <tr>
                        <td style="background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%); padding: 40px 40px 30px; text-align: center;">
                            <div style="font-size: 48px; margin-bottom: 16px;">🌿</div>
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">Your Collection Is Growing!</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 40px;">
                            <p style="margin: 0 0 24px; color: #57534e; font-size: 16px; line-height: 1.6;">
                                You now have <strong>{plant_count} plants</strong> in your collection! 🎉
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 24px; background-color: #ecfdf5; border-radius: 8px; text-align: center;">
                                        <p style="margin: 0; color: #065f46; font-size: 48px; font-weight: bold;">
                                            {plant_count}
                                        </p>
                                        <p style="margin: 8px 0 0; color: #065f46; font-size: 14px;">
                                            plants in your care
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0 0 16px; color: #57534e; font-size: 14px; line-height: 1.6;">
                                As your collection grows, here are some tips to stay organized:
                            </p>

                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 0 0 24px;">
                                <tr>
                                    <td style="padding: 16px; background-color: #f4f1ed; border-radius: 8px;">
                                        <p style="margin: 0 0 8px; color: #44403c; font-size: 14px;">
                                            ✓ Group plants with similar water needs together
                                        </p>
                                        <p style="margin: 0 0 8px; color: #44403c; font-size: 14px;">
                                            ✓ Use our location tags to track where each plant lives
                                        </p>
                                        <p style="margin: 0; color: #44403c; font-size: 14px;">
                                            ✓ Check your reminders regularly — more plants = more care!
                                        </p>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0; color: #57534e; font-size: 14px; line-height: 1.5;">
                                Happy growing! 🌿<br>
                                Ellen
                            </p>
                        </td>
                    </tr>
{_get_email_footer(unsubscribe_url)}
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = f"""Your Collection Is Growing! 🌿

You now have {plant_count} plants in your collection! 🎉

{plant_count} plants in your care

As your collection grows, here are some tips to stay organized:

✓ Group plants with similar water needs together
✓ Use our location tags to track where each plant lives
✓ Check your reminders regularly — more plants = more care!

Happy growing! 🌿
Ellen

---
To unsubscribe from marketing emails, visit your account settings.
"""

    return {
        "subject": "🌿 Your collection is growing!",
        "html": html_content,
        "text": text_content
    }


def send_welcome_email(
    user_id: str, email: str, email_type: str
) -> Dict[str, Any]:
    """
    Send a welcome email and record it to prevent duplicates.

    Args:
        user_id: User's UUID
        email: User's email address
        email_type: One of WELCOME_DAY_0, WELCOME_DAY_3, WELCOME_DAY_7

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    from app.services.supabase_client import get_admin_client

    # Check if already sent (use admin client to bypass RLS)
    try:
        client = get_admin_client()
        if not client:
            return {"success": False, "error": "database_not_configured"}

        existing = (
            client.table("welcome_emails_sent")
            .select("id")
            .eq("user_id", user_id)
            .eq("email_type", email_type)
            .execute()
        )

        if existing.data:
            _safe_log_info(f"Welcome email {email_type} already sent to {user_id}")
            return {"success": True, "message": "already_sent"}

    except Exception as e:
        _safe_log_error(f"Error checking welcome email history: {e}")
        # Continue anyway - we'll try to insert and let the unique constraint catch duplicates

    # Generate unsubscribe URL
    unsubscribe_url = get_unsubscribe_url(user_id)

    # Get email content based on type
    if email_type == WELCOME_DAY_0:
        email_content = _get_welcome_day0_email(unsubscribe_url)
    elif email_type == WELCOME_DAY_3:
        email_content = _get_welcome_day3_email(unsubscribe_url)
    elif email_type == WELCOME_DAY_7:
        email_content = _get_welcome_day7_email(unsubscribe_url)
    elif email_type == WELCOME_DAY_10:
        email_content = _get_welcome_day10_email(unsubscribe_url)
    elif email_type == REENGAGEMENT_14DAY:
        email_content = _get_reengagement_14day_email(unsubscribe_url)
    elif email_type == SEASONAL_SPRING:
        email_content = _get_seasonal_spring_email(unsubscribe_url)
    elif email_type == SEASONAL_SUMMER:
        email_content = _get_seasonal_summer_email(unsubscribe_url)
    elif email_type == SEASONAL_FALL:
        email_content = _get_seasonal_fall_email(unsubscribe_url)
    elif email_type == SEASONAL_WINTER:
        email_content = _get_seasonal_winter_email(unsubscribe_url)
    else:
        return {"success": False, "error": f"unknown_email_type: {email_type}"}

    # Send email via Resend API using shared helper
    result = _send_via_resend(
        to_email=email,
        subject=email_content["subject"],
        html_content=email_content["html"],
        text_content=email_content["text"],
        unsubscribe_url=unsubscribe_url
    )

    if result.get("success"):
        # Record that we sent the email
        try:
            client.table("welcome_emails_sent").insert(
                {"user_id": user_id, "email_type": email_type}
            ).execute()
        except Exception as e:
            # If insert fails due to duplicate, that's fine
            if "duplicate key" not in str(e) and "23505" not in str(e):
                _safe_log_error(f"Error recording welcome email: {e}")

        _safe_log_info(f"Welcome email {email_type} sent to {_mask_email(email)}")

    return result


def get_pending_welcome_emails() -> List[Dict[str, Any]]:
    """
    Get users who are due for welcome emails.

    Returns list of dicts with user_id, email, and email_type needed.
    """
    from app.services.supabase_client import get_admin_client

    pending = []
    now = datetime.now(timezone.utc)

    try:
        # Use admin client to bypass RLS (profiles table has RLS enabled)
        client = get_admin_client()
        if not client:
            return pending

        # Get all users with marketing_opt_in = True
        result = client.table("profiles").select(
            "id, email, marketing_opt_in, created_at"
        ).eq("marketing_opt_in", True).execute()

        if not result.data:
            return pending

        # Get all welcome emails already sent
        sent_result = client.table("welcome_emails_sent").select(
            "user_id, email_type"
        ).execute()

        sent_emails = set()
        if sent_result.data:
            for row in sent_result.data:
                sent_emails.add((row["user_id"], row["email_type"]))

        # Check each user for pending emails
        for user in result.data:
            user_id = user["id"]
            email = user.get("email")
            created_at_str = user.get("created_at")

            if not email or not created_at_str:
                continue

            # Parse created_at
            try:
                created_at = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue

            days_since_signup = (now - created_at).days

            # Day 0: Send immediately if not sent
            if (user_id, WELCOME_DAY_0) not in sent_emails:
                pending.append({
                    "user_id": user_id,
                    "email": email,
                    "email_type": WELCOME_DAY_0,
                })

            # Day 3: Send after 3 days if not sent
            if days_since_signup >= 3 and (user_id, WELCOME_DAY_3) not in sent_emails:
                pending.append({
                    "user_id": user_id,
                    "email": email,
                    "email_type": WELCOME_DAY_3,
                })

            # Day 7: Send after 7 days if not sent
            if days_since_signup >= 7 and (user_id, WELCOME_DAY_7) not in sent_emails:
                pending.append({
                    "user_id": user_id,
                    "email": email,
                    "email_type": WELCOME_DAY_7,
                })

            # Day 10: Send after 10 days if not sent
            if days_since_signup >= 10 and (user_id, WELCOME_DAY_10) not in sent_emails:
                pending.append({
                    "user_id": user_id,
                    "email": email,
                    "email_type": WELCOME_DAY_10,
                })

    except Exception as e:
        _safe_log_error(f"Error getting pending welcome emails: {e}")

    return pending


def get_pending_reengagement_emails() -> List[Dict[str, Any]]:
    """
    Get users who are due for re-engagement emails.

    Criteria:
    - marketing_opt_in = True
    - No login for 14+ days (uses Supabase auth.users last_sign_in_at)
    - Haven't received this email in the last 30 days

    Returns list of dicts with user_id, email, and email_type.
    """
    from app.services.supabase_client import get_admin_client

    pending = []
    now = datetime.now(timezone.utc)

    try:
        client = get_admin_client()
        if not client:
            return pending

        # Get all users with marketing_opt_in = True
        profiles_result = client.table("profiles").select(
            "id, email, marketing_opt_in"
        ).eq("marketing_opt_in", True).execute()

        if not profiles_result.data:
            return pending

        # Get re-engagement emails sent in last 30 days
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        sent_result = client.table("welcome_emails_sent").select(
            "user_id, email_type, sent_at"
        ).eq("email_type", REENGAGEMENT_14DAY).gte(
            "sent_at", thirty_days_ago
        ).execute()

        recently_sent = set()
        if sent_result.data:
            for row in sent_result.data:
                recently_sent.add(row["user_id"])

        # Get last sign in times from auth.users via admin API
        # We'll use Supabase's auth.admin.list_users() to get this
        try:
            users_response = client.auth.admin.list_users()
            auth_users = {u.id: u for u in users_response}
        except Exception as e:
            _safe_log_error(f"Error fetching auth users: {e}")
            return pending

        # Check each user for inactivity
        for profile in profiles_result.data:
            user_id = profile["id"]
            email = profile.get("email")

            if not email or user_id in recently_sent:
                continue

            # Get last sign in from auth users
            auth_user = auth_users.get(user_id)
            if not auth_user or not auth_user.last_sign_in_at:
                continue

            # Parse last sign in time
            try:
                last_sign_in = datetime.fromisoformat(
                    auth_user.last_sign_in_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError, AttributeError):
                continue

            days_since_login = (now - last_sign_in).days

            # Send if inactive for 14+ days
            if days_since_login >= 14:
                pending.append({
                    "user_id": user_id,
                    "email": email,
                    "email_type": REENGAGEMENT_14DAY,
                })

    except Exception as e:
        _safe_log_error(f"Error getting pending re-engagement emails: {e}")

    return pending


def get_user_hemisphere(user_id: str) -> str:
    """
    Determine user's hemisphere from profile or weather data.

    Priority:
    1. Explicit hemisphere preference in profile
    2. Auto-detect from city latitude
    3. Default to 'northern' if unknown

    Args:
        user_id: User's UUID

    Returns:
        'northern' or 'southern'
    """
    from app.services.supabase_client import get_user_profile
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


def get_current_season_for_hemisphere(
    hemisphere: str = 'northern'
) -> Optional[tuple[str, str]]:
    """
    Get current season email type and season_year key if in a sending window.

    Sending windows are the 1st-15th of:
    - March, June, September, November

    The season returned depends on hemisphere:
    - Northern: March=Spring, June=Summer, Sept=Fall, Nov=Winter
    - Southern: March=Fall, June=Winter, Sept=Spring, Nov=Summer

    Args:
        hemisphere: 'northern' or 'southern'

    Returns:
        Tuple of (email_type, season_year) if in window, None otherwise
        Example: (SEASONAL_SPRING, "spring_2026")
    """
    now = datetime.now(timezone.utc)
    month = now.month
    day = now.day
    year = now.year

    # Check if we're in a sending window (1st-15th of the month)
    if day > 15:
        return None

    # Northern hemisphere mapping
    northern_seasons = {
        3: (SEASONAL_SPRING, f"spring_{year}"),
        6: (SEASONAL_SUMMER, f"summer_{year}"),
        9: (SEASONAL_FALL, f"fall_{year}"),
        11: (SEASONAL_WINTER, f"winter_{year}"),
    }

    # Southern hemisphere - seasons are flipped
    southern_seasons = {
        3: (SEASONAL_FALL, f"fall_{year}"),      # March = Fall in Southern
        6: (SEASONAL_WINTER, f"winter_{year}"),  # June = Winter in Southern
        9: (SEASONAL_SPRING, f"spring_{year}"),  # Sept = Spring in Southern
        11: (SEASONAL_SUMMER, f"summer_{year}"), # Nov = Summer in Southern
    }

    seasons = southern_seasons if hemisphere == 'southern' else northern_seasons
    return seasons.get(month)


def get_current_season() -> Optional[tuple[str, str]]:
    """
    Get the current season email type and season_year key if in a sending window.

    DEPRECATED: Use get_current_season_for_hemisphere() for hemisphere-aware logic.

    Sending windows (Northern Hemisphere):
    - Spring: March 1-15
    - Summer: June 1-15
    - Fall: September 1-15
    - Winter: November 1-15

    Returns:
        Tuple of (email_type, season_year) if in window, None otherwise
        Example: (SEASONAL_SPRING, "spring_2026")
    """
    return get_current_season_for_hemisphere('northern')


def get_pending_seasonal_emails() -> List[Dict[str, Any]]:
    """
    Get users who are due for seasonal emails (hemisphere-aware).

    Only sends during the appropriate seasonal window (1st-15th of March,
    June, September, or November) and only once per season.

    Each user receives the seasonal email appropriate for their hemisphere:
    - Northern hemisphere: March=Spring, June=Summer, Sept=Fall, Nov=Winter
    - Southern hemisphere: March=Fall, June=Winter, Sept=Spring, Nov=Summer

    Uses seasonal_emails_sent table to track what's been sent.

    Returns list of dicts with user_id, email, email_type, and season_year.
    """
    from app.services.supabase_client import get_admin_client

    pending = []

    # First check if we're in a sending window at all
    # Both hemispheres send in the same months, just different season names
    now = datetime.now(timezone.utc)
    month = now.month
    day = now.day

    if day > 15 or month not in (3, 6, 9, 11):
        return pending

    try:
        client = get_admin_client()
        if not client:
            return pending

        # Get all users with marketing_opt_in = True
        profiles_result = client.table("profiles").select(
            "id, email, marketing_opt_in, hemisphere, city"
        ).eq("marketing_opt_in", True).execute()

        if not profiles_result.data:
            return pending

        # Get ALL seasonal emails sent (we'll filter per-user)
        try:
            sent_result = client.table("seasonal_emails_sent").select(
                "user_id, season_year"
            ).execute()

            # Build set of (user_id, season_year) tuples
            already_sent = set()
            if sent_result.data:
                for row in sent_result.data:
                    already_sent.add((row["user_id"], row["season_year"]))
        except Exception:
            # Table might not exist yet
            already_sent = set()

        # Check each user - determine their hemisphere and appropriate season
        for profile in profiles_result.data:
            user_id = profile["id"]
            email = profile.get("email")

            if not email:
                continue

            # Get user's hemisphere
            hemisphere = get_user_hemisphere(user_id)

            # Get the correct season for this user's hemisphere
            season_info = get_current_season_for_hemisphere(hemisphere)
            if not season_info:
                continue

            email_type, season_year = season_info

            # Check if this user already received this season's email
            if (user_id, season_year) in already_sent:
                continue

            pending.append({
                "user_id": user_id,
                "email": email,
                "email_type": email_type,
                "season_year": season_year,
            })

    except Exception as e:
        _safe_log_error(f"Error getting pending seasonal emails: {e}")

    return pending


def send_seasonal_email(
    user_id: str, email: str, email_type: str, season_year: str
) -> Dict[str, Any]:
    """
    Send a seasonal email and record it to prevent duplicates.

    Args:
        user_id: User's UUID
        email: User's email address
        email_type: One of SEASONAL_SPRING, SEASONAL_SUMMER, etc.
        season_year: Key like "spring_2026" to track what's been sent

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    from app.services.supabase_client import get_admin_client

    # Use the main send function for the actual sending
    result = send_welcome_email(user_id, email, email_type)

    if result.get("success") and result.get("message") != "already_sent":
        # Record in seasonal_emails_sent table
        try:
            client = get_admin_client()
            if client:
                client.table("seasonal_emails_sent").insert({
                    "user_id": user_id,
                    "season_year": season_year
                }).execute()
        except Exception as e:
            # Log but don't fail - the email was sent
            _safe_log_error(f"Error recording seasonal email: {e}")

    return result


def process_welcome_email_queue() -> Dict[str, Any]:
    """
    Process all pending welcome, re-engagement, seasonal, and milestone emails.

    Called by the scheduler to send marketing emails in batches.

    Returns:
        Dict with counts of sent, failed, and skipped emails
    """
    stats = {"sent": 0, "failed": 0, "skipped": 0}

    if not _is_marketing_enabled():
        return stats

    try:
        # Get all pending emails (welcome series + re-engagement)
        pending = get_pending_welcome_emails()
        pending.extend(get_pending_reengagement_emails())

        _safe_log_info(f"Processing {len(pending)} pending marketing emails")

        for item in pending:
            result = send_welcome_email(
                item["user_id"], item["email"], item["email_type"]
            )

            if result.get("success"):
                if result.get("message") == "already_sent":
                    stats["skipped"] += 1
                else:
                    stats["sent"] += 1
            else:
                stats["failed"] += 1

        # Process seasonal emails separately (uses different tracking table)
        seasonal_pending = get_pending_seasonal_emails()
        if seasonal_pending:
            _safe_log_info(f"Processing {len(seasonal_pending)} pending seasonal emails")

            for item in seasonal_pending:
                result = send_seasonal_email(
                    item["user_id"],
                    item["email"],
                    item["email_type"],
                    item["season_year"]
                )

                if result.get("success"):
                    if result.get("message") == "already_sent":
                        stats["skipped"] += 1
                    else:
                        stats["sent"] += 1
                else:
                    stats["failed"] += 1

        # Check for plant anniversaries (triggers events for later processing)
        check_plant_anniversaries()

        # Process milestone emails (uses email_events table)
        milestone_pending = get_pending_milestone_emails()
        if milestone_pending:
            _safe_log_info(f"Processing {len(milestone_pending)} pending milestone emails")

            for item in milestone_pending:
                result = send_milestone_email(
                    item["user_id"],
                    item["email"],
                    item["event_type"],
                    item.get("event_data")
                )

                if result.get("success"):
                    stats["sent"] += 1
                else:
                    stats["failed"] += 1

    except Exception as e:
        _safe_log_error(f"Error processing marketing email queue: {e}")

    _safe_log_info(
        f"Marketing email queue processed: {stats['sent']} sent, "
        f"{stats['failed']} failed, {stats['skipped']} skipped"
    )
    return stats


def trigger_milestone_event(
    user_id: str,
    event_type: str,
    event_data: Optional[Dict[str, Any]] = None,
    event_key: str = "once"
) -> bool:
    """
    Record a milestone event for later email processing.
    Uses upsert to guarantee idempotency.

    Args:
        user_id: User's UUID
        event_type: One of MILESTONE_FIRST_PLANT, MILESTONE_ANNIVERSARY_30, etc.
        event_data: Optional data like plant_name, streak_count, plant_count
        event_key: A stable idempotency key for each milestone event

    Returns:
        True if event was recorded, False otherwise
    """
    if not _is_marketing_enabled():
        return False

    from app.services.supabase_client import get_admin_client
    from app.utils.validation import is_valid_uuid

    if not is_valid_uuid(user_id):
        _safe_log_error(f"Invalid UUID passed to trigger_milestone_event: {user_id!r}")
        return False

    try:
        client = get_admin_client()
        if not client:
            return False

        client.table("email_events").upsert(
            {
                "user_id": user_id,
                "event_type": event_type,
                "event_data": event_data,
                "event_key": event_key,
            },
            on_conflict="user_id,event_type,event_key",
        ).execute()
        
        _safe_log_info(f"Milestone event {event_type} recorded for user {user_id} (key={event_key})")
        return True

    except Exception as e:
        _safe_log_error(f"Error recording milestone event: {e}")
        return False


def send_milestone_email(
    user_id: str,
    email: str,
    event_type: str,
    event_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Send a milestone email and mark the event as sent.

    Args:
        user_id: User's UUID
        email: User's email address
        event_type: One of MILESTONE_FIRST_PLANT, MILESTONE_ANNIVERSARY_30, etc.
        event_data: Optional data like plant_name, streak_count, plant_count

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    from app.services.supabase_client import get_admin_client

    # Generate unsubscribe URL
    unsubscribe_url = get_unsubscribe_url(user_id)

    # Get email content based on type
    if event_type == MILESTONE_FIRST_PLANT:
        email_content = _get_milestone_first_plant_email(unsubscribe_url)
    elif event_type == MILESTONE_ANNIVERSARY_30:
        plant_name = event_data.get("plant_name", "Your plant") if event_data else "Your plant"
        email_content = _get_milestone_anniversary_30_email(unsubscribe_url, plant_name)
    elif event_type == MILESTONE_STREAK_5:
        streak_count = event_data.get("streak_count", 5) if event_data else 5
        email_content = _get_milestone_streak_5_email(unsubscribe_url, streak_count)
    elif event_type == MILESTONE_COLLECTION_5:
        plant_count = event_data.get("plant_count", 5) if event_data else 5
        email_content = _get_milestone_collection_5_email(unsubscribe_url, plant_count)
    else:
        return {"success": False, "error": f"unknown_event_type: {event_type}"}

    # Send email via Resend API using shared helper
    result = _send_via_resend(
        to_email=email,
        subject=email_content["subject"],
        html_content=email_content["html"],
        text_content=email_content["text"],
        unsubscribe_url=unsubscribe_url
    )

    if result.get("success"):
        # Mark the event as sent
        try:
            client = get_admin_client()
            if client:
                client.table("email_events").update({
                    "email_sent_at": datetime.now(timezone.utc).isoformat()
                }).eq("user_id", user_id).eq(
                    "event_type", event_type
                ).is_("email_sent_at", "null").execute()
        except Exception as e:
            _safe_log_error(f"Error marking milestone event as sent: {e}")

        _safe_log_info(f"Milestone email {event_type} sent to {_mask_email(email)}")

    return result


def get_pending_milestone_emails() -> List[Dict[str, Any]]:
    """
    Get pending milestone emails that need to be sent.

    Returns list of dicts with user_id, email, event_type, and event_data.
    """
    from app.services.supabase_client import get_admin_client

    pending = []

    try:
        client = get_admin_client()
        if not client:
            return pending

        # Get unsent events
        events_result = client.table("email_events").select(
            "user_id, event_type, event_data"
        ).is_("email_sent_at", "null").execute()

        if not events_result.data:
            return pending

        # Get user emails and check marketing opt-in (filter out invalid UUIDs)
        from app.utils.validation import is_valid_uuid
        user_ids = list(set(
            e["user_id"] for e in events_result.data if is_valid_uuid(e.get("user_id"))
        ))

        if not user_ids:
            return pending

        profiles_result = client.table("profiles").select(
            "id, email, marketing_opt_in"
        ).in_("id", user_ids).eq("marketing_opt_in", True).execute()

        if not profiles_result.data:
            return pending

        # Build user lookup
        users = {p["id"]: p for p in profiles_result.data}

        # Match events to users
        for event in events_result.data:
            user = users.get(event["user_id"])
            if user and user.get("email"):
                pending.append({
                    "user_id": event["user_id"],
                    "email": user["email"],
                    "event_type": event["event_type"],
                    "event_data": event["event_data"]
                })

    except Exception as e:
        _safe_log_error(f"Error getting pending milestone emails: {e}")

    return pending


def check_watering_streak(user_id: str) -> None:
    """
    Check if user has reached a watering streak milestone and trigger email.

    Streak milestones: 5, 7, 14, 30, 60, 100 days
    """
    from app.services.supabase_client import get_admin_client
    from app.utils.validation import is_valid_uuid

    if not is_valid_uuid(user_id):
        return

    try:
        client = get_admin_client()
        if not client:
            return

        # Get plant actions from the last 100 days to calculate streak
        now = datetime.now(timezone.utc)
        hundred_days_ago = now - timedelta(days=100)

        result = client.table("plant_actions").select(
            "action_at"
        ).eq("user_id", user_id).gte(
            "action_at", hundred_days_ago.isoformat()
        ).order("action_at", desc=True).execute()

        if not result.data:
            return

        # Calculate consecutive days with activity
        activity_dates = set()
        for action in result.data:
            try:
                action_date = datetime.fromisoformat(
                    action["action_at"].replace("Z", "+00:00")
                ).date()
                activity_dates.add(action_date)
            except (ValueError, TypeError):
                continue

        if not activity_dates:
            return

        # Count streak from today backwards
        streak = 0
        current_date = now.date()

        # Allow for today or yesterday as the streak start
        if current_date in activity_dates:
            check_date = current_date
        elif (current_date - timedelta(days=1)) in activity_dates:
            check_date = current_date - timedelta(days=1)
        else:
            return  # No recent activity

        while check_date in activity_dates:
            streak += 1
            check_date = check_date - timedelta(days=1)

        # Trigger milestone for specific streak values
        streak_milestones = [5, 7, 14, 30, 60, 100]
        if streak in streak_milestones:
            trigger_milestone_event(
                user_id,
                MILESTONE_STREAK_5,
                {"streak_count": streak},
                event_key=f"days:{streak}"
            )

    except Exception as e:
        _safe_log_error(f"Error checking watering streak: {e}")


def check_plant_anniversaries() -> None:
    """
    Check for plants that have reached their 30-day anniversary.

    Called by scheduler to trigger anniversary milestone events.
    """
    from app.services.supabase_client import get_admin_client

    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    # Check plants created between 30-31 days ago
    thirty_one_days_ago = now - timedelta(days=31)

    try:
        client = get_admin_client()
        if not client:
            return

        # Get plants created around 30 days ago
        result = client.table("plants").select(
            "id, user_id, name, nickname, species, created_at"
        ).gte(
            "created_at", thirty_one_days_ago.isoformat()
        ).lte(
            "created_at", thirty_days_ago.isoformat()
        ).execute()

        if not result.data:
            return

        for plant in result.data:
            plant_name = plant.get("nickname") or plant.get("name") or plant.get("species") or "Your plant"
            trigger_milestone_event(
                plant["user_id"],
                MILESTONE_ANNIVERSARY_30,
                {"plant_name": plant_name, "plant_id": plant["id"]},
                event_key=f"plant:{plant['id']}:30d"
            )

    except Exception as e:
        _safe_log_error(f"Error checking plant anniversaries: {e}")


def sync_to_resend_audience(email: str, subscribed: bool) -> bool:
    """
    Sync a contact to/from the Resend Audience for campaign management.

    Args:
        email: User's email address
        subscribed: True to add, False to remove

    Returns:
        True if successful, False otherwise
    """
    if not _is_marketing_enabled():
        return True

    api_key = os.getenv("RESEND_API_KEY")
    audience_id = os.getenv("RESEND_AUDIENCE_ID")

    if not api_key or not audience_id:
        _safe_log_info("Resend Audience not configured, skipping sync")
        return True  # Not an error, just not configured

    try:
        if subscribed:
            # Add contact to audience
            response = requests.post(
                f"https://api.resend.com/audiences/{audience_id}/contacts",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"email": email},
                timeout=10,
            )
        else:
            # Remove contact from audience
            response = requests.delete(
                f"https://api.resend.com/audiences/{audience_id}/contacts/{email}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )

        if response.status_code in (200, 201, 204):
            action = "added to" if subscribed else "removed from"
            _safe_log_info(f"Contact {_mask_email(email)} {action} Resend Audience")
            return True
        else:
            _safe_log_error(
                f"Resend Audience sync failed: {response.status_code} - {response.text}"
            )
            return False

    except Exception as e:
        _safe_log_error(f"Error syncing to Resend Audience: {e}")
        return False
