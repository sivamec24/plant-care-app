"""
Marketing landing pages and email management.

Provides:
- SEO landing pages (AI Plant Doctor)
- Sitemap and robots.txt
- Email unsubscribe functionality
"""

from __future__ import annotations
from flask import Blueprint, render_template, Response, current_app
from xml.sax.saxutils import escape
from app.utils.data import load_data_file
import os


marketing_bp = Blueprint("marketing", __name__)

# Load once at import time for sitemap generation
_SEO_PAGES = load_data_file("seo_landing_pages.json")
_HUB_PAGES = load_data_file("seo_hub_pages.json")
_GUIDES = load_data_file("guides.json")

# Sitemap lastmod dates for static pages (not driven by JSON data files).
# Update these when deploying changes that affect the corresponding page.
# Legal pages (terms, privacy) are read from config.LEGAL_LAST_UPDATED instead.
# JSON-driven pages (landing, hub, guides) use their own `last_updated` field.
STATIC_PAGE_DATES = {
    "/": "2026-02-21",
    "/ask": "2026-01-30",
    "/ai-plant-doctor": "2025-12-18",
    "/plant-care-guides/": "2026-02-21",
    "/features/": "2026-01-30",
}


@marketing_bp.route("/ai-plant-doctor")
def ai_plant_doctor():
    """
    SEO landing page for AI Plant Doctor feature.

    Targets keywords: "AI plant care", "plant care assistant", "plant doctor"
    Links to /ask for the actual tool.
    """
    return render_template("marketing/ai-plant-doctor.html")


@marketing_bp.route("/sitemap.xml")
def sitemap():
    """
    Dynamic XML sitemap for search engines.

    Lists all public pages with priority and change frequency.
    """
    # Use configured base URL (not request.url_root to prevent Host header injection)
    base_url = os.getenv("APP_URL", "https://plantcareai.app")

    # Static pages — dates from STATIC_PAGE_DATES dict
    # OG image filenames for static pages that have unique images
    _STATIC_IMAGES = {
        "/": "home.png",
        "/ask": "ask.png",
        "/ai-plant-doctor": "plant-doctor.png",
        "/plant-care-guides/": "guides-index.png",
        "/features/": "features.png",
    }
    pages = []
    for loc, p, cf in [
        ("/", "1.0", "weekly"),
        ("/ask", "0.9", "weekly"),
        ("/ai-plant-doctor", "0.9", "monthly"),
        ("/plant-care-guides/", "0.8", "weekly"),
        ("/features/", "0.8", "monthly"),
    ]:
        entry = {"loc": loc, "priority": p, "changefreq": cf, "lastmod": STATIC_PAGE_DATES[loc]}
        if loc in _STATIC_IMAGES:
            entry["image"] = f"{base_url}/static/images/og/{_STATIC_IMAGES[loc]}"
            entry["image_title"] = "PlantCareAI"
        pages.append(entry)
    # Legal pages — date synced from LEGAL_LAST_UPDATED config
    legal_date = current_app.config.get("LEGAL_LAST_UPDATED", "2026-02-15")
    pages.extend([
        {"loc": "/terms", "priority": "0.3", "changefreq": "yearly", "lastmod": legal_date},
        {"loc": "/privacy", "priority": "0.3", "changefreq": "yearly", "lastmod": legal_date},
    ])

    # SEO landing pages (problem-first content pages, from seo_landing_pages.json)
    for page in _SEO_PAGES:
        pages.append({
            "loc": f"/{page['slug']}",
            "priority": "0.8",
            "changefreq": "monthly",
            "lastmod": page.get("last_updated", "2026-01-30"),
            "image": f"{base_url}/static/images/og/seo-{page['slug']}.png",
            "image_title": page.get("title", ""),
        })

    # SEO hub/pillar pages (from seo_hub_pages.json)
    for page in _HUB_PAGES:
        pages.append({
            "loc": f"/{page['slug']}",
            "priority": "0.9",
            "changefreq": "monthly",
            "lastmod": page.get("last_updated", "2026-02-09"),
            "image": f"{base_url}/static/images/og/hub-{page['slug']}.png",
            "image_title": page.get("title", ""),
        })

    # Individual guide pages (from guides.json)
    for guide in _GUIDES:
        if guide.get("slug"):
            pages.append({
                "loc": f"/plant-care-guides/{guide['slug']}",
                "priority": "0.7",
                "changefreq": "monthly",
                "lastmod": guide.get("last_updated", "2025-12-18"),
                "image": f"{base_url}/static/images/og/guide-{guide['slug']}.png",
                "image_title": f"{guide.get('name', '')} Care Guide",
            })

    # Build XML (with image sitemap extension)
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    xml_content += ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'

    for page in pages:
        xml_content += "  <url>\n"
        xml_content += f"    <loc>{escape(base_url + page['loc'])}</loc>\n"
        xml_content += f"    <lastmod>{escape(page['lastmod'])}</lastmod>\n"
        xml_content += f"    <changefreq>{escape(page['changefreq'])}</changefreq>\n"
        xml_content += f"    <priority>{escape(page['priority'])}</priority>\n"
        if "image" in page:
            xml_content += "    <image:image>\n"
            xml_content += f"      <image:loc>{escape(page['image'])}</image:loc>\n"
            xml_content += f"      <image:title>{escape(page['image_title'])}</image:title>\n"
            xml_content += "    </image:image>\n"
        xml_content += "  </url>\n"

    xml_content += "</urlset>"

    return Response(xml_content, mimetype="application/xml")


@marketing_bp.route("/robots.txt")
def robots():
    """
    Serve robots.txt from root URL.

    Search engines expect this at /robots.txt, not /static/robots.txt.
    """
    robots_path = os.path.join(current_app.static_folder, "robots.txt")
    try:
        with open(robots_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        # Provide sensible default if file is missing
        content = "User-agent: *\nAllow: /"
    return Response(content, mimetype="text/plain")


@marketing_bp.route("/unsubscribe/<token>")
def unsubscribe(token: str):
    """
    One-click unsubscribe from marketing emails.

    Token is a signed user_id that expires after 30 days.
    Shows a confirmation page after unsubscribing.
    """
    from app.services.marketing_emails import verify_unsubscribe_token, sync_to_resend_audience
    from app.services import supabase_client

    # Verify token
    user_id = verify_unsubscribe_token(token)

    if not user_id:
        return render_template(
            "marketing/unsubscribe.html",
            success=False,
            error="This unsubscribe link has expired or is invalid. Please visit your account settings to manage email preferences.",
        )

    # Get user profile
    profile = supabase_client.get_user_profile(user_id)

    if not profile:
        return render_template(
            "marketing/unsubscribe.html",
            success=False,
            error="We couldn't find your account. Please visit your account settings to manage email preferences.",
        )

    # Check if already unsubscribed
    if not profile.get("marketing_opt_in", False):
        return render_template(
            "marketing/unsubscribe.html",
            success=True,
            already_unsubscribed=True,
        )

    # Unsubscribe the user
    success, error = supabase_client.update_marketing_preference(
        user_id, marketing_opt_in=False
    )

    if success:
        # Remove from Resend Audience
        email = profile.get("email")
        if email:
            sync_to_resend_audience(email, subscribed=False)

        return render_template(
            "marketing/unsubscribe.html",
            success=True,
            already_unsubscribed=False,
        )
    else:
        return render_template(
            "marketing/unsubscribe.html",
            success=False,
            error="Something went wrong. Please try again or visit your account settings.",
        )
