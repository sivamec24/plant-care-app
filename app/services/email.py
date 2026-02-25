"""
Email service using Resend for transactional emails.

Provides:
- OTP verification code emails
- Future: Welcome emails, reminder notifications, etc.
"""

from __future__ import annotations
from typing import Dict, Any
import os
import requests
from flask import current_app, has_app_context
from app.utils.sanitize import mask_email as _mask_email


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


def send_otp_email(email: str, code: str) -> Dict[str, Any]:
    """
    Send OTP verification code via Resend.

    Args:
        email: Recipient email address
        code: 6-digit OTP code

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    # Get API key from environment
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        _safe_log_error("RESEND_API_KEY not configured")
        return {
            "success": False,
            "error": "email_not_configured",
            "message": "Email service not configured"
        }

    # Prepare email HTML (clean, simple design)
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PlantCareAI Verification Code</title>
</head>
<body style="margin:0; padding:0; background-color:#ffffff; font-family:Arial, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
    <tr>
      <td align="center" style="padding:24px;">
        <table width="600" cellpadding="0" cellspacing="0" role="presentation" style="width:100%; max-width:600px;">
          <tr>
            <td style="padding:0 0 16px; font-size:18px; font-weight:bold; color:#111827;">
              PlantCareAI
            </td>
          </tr>

          <tr>
            <td style="padding:0 0 12px; font-size:16px; font-weight:bold; color:#111827;">
              Your verification code
            </td>
          </tr>

          <tr>
            <td style="padding:0 0 16px; font-size:14px; color:#44403c; line-height:1.5;">
              Enter this code to sign in:
            </td>
          </tr>

          <tr>
            <td style="padding:16px; border:1px solid #e8e3dd; border-radius:6px; text-align:center;">
              <div style="font-size:32px; font-weight:bold; letter-spacing:4px; color:#111827;">
                {code}
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:16px 0 0; font-size:13px; color:#78716c; line-height:1.5;">
              This code expires in 15 minutes. Don’t share it with anyone.
            </td>
          </tr>

          <tr>
            <td style="padding:16px 0 0; font-size:13px; color:#78716c; line-height:1.5;">
              If you didn’t request this, you can safely ignore this email.
            </td>
          </tr>

          <tr>
            <td style="padding:24px 0 0; font-size:12px; color:#a69d91; line-height:1.5;">
              Automated message from PlantCareAI.
              Need help? support@plantcareai.app
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    # Plain text version (for email clients that don't support HTML)
    text_content = f"""PlantCareAI
    
Your verification code

Enter this code to sign in:
{code}

This code expires in 15 minutes. Don’t share it with anyone.

If you didn’t request this, you can safely ignore this email.

---
Automated message from PlantCareAI.
Need help? support@plantcareai.app
"""

    # Send email via Resend API
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "from": "PlantCareAI <verify@updates.plantcareai.app>",
                "to": [email],
                "subject": "Your PlantCareAI verification code is ready",
                "html": html_content,
                "text": text_content,
            },
            timeout=10
        )

        if response.status_code == 200:
            _safe_log_info(f"OTP email sent successfully to {_mask_email(email)}")
            return {
                "success": True,
                "message": f"Verification code sent to {email}"
            }
        else:
            error_data = response.json() if response.text else {}
            error_message = error_data.get("message", "Unknown error")
            _safe_log_error(f"Resend API error: {response.status_code} - {error_message}")

            # Check for rate limiting
            if response.status_code == 429:
                return {
                    "success": False,
                    "error": "rate_limit",
                    "message": "Too many emails sent. Please wait a few minutes and try again."
                }

            return {
                "success": False,
                "error": "email_send_failed",
                "message": "Our email service is temporarily unavailable. Please try again in a few minutes."
            }

    except requests.exceptions.Timeout:
        _safe_log_error("Resend API timeout")
        return {
            "success": False,
            "error": "timeout",
            "message": "Our email service is temporarily unavailable. Please try again in a few minutes."
        }
    except requests.exceptions.ConnectionError:
        _safe_log_error("Resend API connection error (service may be down)")
        return {
            "success": False,
            "error": "service_unavailable",
            "message": "Our email service is temporarily unavailable. Please try again in a few minutes."
        }
    except Exception as e:
        _safe_log_error(f"Error sending email via Resend: {e}")
        return {
            "success": False,
            "error": "unknown",
            "message": "Unable to send email right now. Please try again later."
        }


def send_legal_update_email(email: str) -> Dict[str, Any]:
    """
    Send a transactional notification about material ToS/Privacy Policy changes.

    This is a service notification (not marketing), so it does NOT check
    MARKETING_EMAILS_ENABLED and is always allowed.

    Args:
        email: Recipient email address

    Returns:
        Dict with 'success' bool and 'message' or 'error'
    """
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        _safe_log_error("RESEND_API_KEY not configured")
        return {
            "success": False,
            "error": "email_not_configured",
            "message": "Email service not configured"
        }

    app_url = os.getenv("APP_URL", "https://plantcareai.app")

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PlantCareAI - Updated Terms &amp; Privacy Policy</title>
</head>
<body style="margin:0; padding:0; background-color:#ffffff; font-family:Arial, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
    <tr>
      <td align="center" style="padding:24px;">
        <table width="600" cellpadding="0" cellspacing="0" role="presentation" style="width:100%; max-width:600px;">
          <tr>
            <td style="padding:0 0 16px; font-size:18px; font-weight:bold; color:#111827;">
              PlantCareAI
            </td>
          </tr>

          <tr>
            <td style="padding:0 0 12px; font-size:16px; font-weight:bold; color:#111827;">
              Important: We've Updated Our Terms &amp; Privacy Policy
            </td>
          </tr>

          <tr>
            <td style="padding:0 0 16px; font-size:14px; color:#44403c; line-height:1.6;">
              We've made significant updates to our
              <a href="{app_url}/terms" style="color:#059669; text-decoration:underline;">Terms of Service</a>
              and
              <a href="{app_url}/privacy" style="color:#059669; text-decoration:underline;">Privacy Policy</a>,
              effective February 15, 2026. Here's a summary of the key changes:
            </td>
          </tr>

          <tr>
            <td style="padding:0 0 16px; font-size:14px; color:#44403c; line-height:1.8;">
              <strong>Privacy Policy updates:</strong><br>
              &bull; Added GDPR legal basis for each data processing activity<br>
              &bull; Added CCPA/CPRA rights for California residents<br>
              &bull; Expanded automated decision-making disclosure (weather-based reminders)<br>
              &bull; Detailed cookie and session information<br>
              &bull; Added international data transfer mechanisms<br>
              &bull; Added third-party data sharing table
            </td>
          </tr>

          <tr>
            <td style="padding:0 0 16px; font-size:14px; color:#44403c; line-height:1.8;">
              <strong>Terms of Service updates:</strong><br>
              &bull; Added AS-IS warranty disclaimer<br>
              &bull; Added weather adjustment disclosure<br>
              &bull; Specified governing law (State of Texas)<br>
              &bull; Added severability and entire agreement clauses<br>
              &bull; Added user termination rights
            </td>
          </tr>

          <tr>
            <td style="padding:16px; border:1px solid #e8e3dd; border-radius:6px; text-align:center;">
              <a href="{app_url}/terms" style="display:inline-block; padding:10px 24px; background-color:#059669; color:#ffffff; text-decoration:none; border-radius:6px; font-weight:bold; font-size:14px;">
                Review the Changes
              </a>
            </td>
          </tr>

          <tr>
            <td style="padding:16px 0 0; font-size:13px; color:#78716c; line-height:1.5;">
              By continuing to use PlantCareAI after February 15, 2026, you agree to the updated terms.
              If you have questions, contact us at support@plantcareai.app.
            </td>
          </tr>

          <tr>
            <td style="padding:24px 0 0; font-size:12px; color:#a69d91; line-height:1.5;">
              This is a service notification about changes to our legal documents.
              You are receiving this because you have a PlantCareAI account.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    text_content = f"""PlantCareAI

Important: We've Updated Our Terms & Privacy Policy

We've made significant updates to our Terms of Service and Privacy Policy,
effective February 15, 2026.

Privacy Policy updates:
- Added GDPR legal basis for each data processing activity
- Added CCPA/CPRA rights for California residents
- Expanded automated decision-making disclosure (weather-based reminders)
- Detailed cookie and session information
- Added international data transfer mechanisms
- Added third-party data sharing table

Terms of Service updates:
- Added AS-IS warranty disclaimer
- Added weather adjustment disclosure
- Specified governing law (State of Texas)
- Added severability and entire agreement clauses
- Added user termination rights

Review the full documents:
- Terms of Service: {app_url}/terms
- Privacy Policy: {app_url}/privacy

By continuing to use PlantCareAI after February 15, 2026, you agree to the
updated terms. If you have questions, contact us at support@plantcareai.app.

---
This is a service notification about changes to our legal documents.
You are receiving this because you have a PlantCareAI account.
"""

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "from": "PlantCareAI <hello@updates.plantcareai.app>",
                "to": [email],
                "subject": "Important: We've Updated Our Terms & Privacy Policy",
                "html": html_content,
                "text": text_content,
            },
            timeout=10
        )

        if response.status_code in (200, 201):
            _safe_log_info(f"Legal update email sent to {_mask_email(email)}")
            return {"success": True, "message": "Legal update email sent"}
        else:
            error_data = response.json() if response.text else {}
            error_message = error_data.get("message", "Unknown error")
            _safe_log_error(f"Resend API error: {response.status_code} - {error_message}")

            if response.status_code == 429:
                return {
                    "success": False,
                    "error": "rate_limit",
                    "message": "Rate limited. Please wait and retry."
                }

            return {
                "success": False,
                "error": "email_send_failed",
                "message": "Our email service is temporarily unavailable. Please try again in a few minutes."
            }

    except requests.exceptions.Timeout:
        _safe_log_error("Resend API timeout sending legal update email")
        return {"success": False, "error": "timeout", "message": "Our email service is temporarily unavailable. Please try again in a few minutes."}
    except requests.exceptions.ConnectionError:
        _safe_log_error("Resend API connection error sending legal update email (service may be down)")
        return {"success": False, "error": "service_unavailable", "message": "Our email service is temporarily unavailable. Please try again in a few minutes."}
    except Exception as e:
        _safe_log_error(f"Error sending legal update email: {e}")
        return {"success": False, "error": "unknown", "message": "Unable to send email right now. Please try again later."}
