"""
Flask CLI commands for one-off administrative tasks.

Usage:
    flask send-legal-notification                    # Dry run (count users)
    flask send-legal-notification --to you@email.com # Test with one email
    flask send-legal-notification --confirm          # Send to all users
    flask generate-og-images                         # Generate missing OG images
    flask generate-og-images --force                 # Regenerate all OG images
"""

from __future__ import annotations

import time

import click
from flask.cli import with_appcontext


@click.command("send-legal-notification")
@click.option("--confirm", is_flag=True, default=False,
              help="Actually send emails. Without this flag, only counts users (dry run).")
@click.option("--to", default=None,
              help="Send a single test email to this address instead of all users.")
@with_appcontext
def send_legal_notification_command(confirm: bool, to: str | None) -> None:
    """Send legal update notification email to all users (one-time)."""
    from app.services import supabase_client
    from app.services.email import send_legal_update_email
    from app.utils.sanitize import mask_email

    # Single-email test mode
    if to:
        click.echo(f"Sending test email to {to}...")
        result = send_legal_update_email(to)
        if result.get("success"):
            click.echo("Test email sent successfully. Check your inbox.")
        else:
            click.echo(f"Failed: {result.get('error', 'unknown')}")
        return

    admin = supabase_client.get_admin_client()
    if not admin:
        click.echo("Error: Supabase admin client not configured (SUPABASE_SERVICE_ROLE_KEY missing).")
        raise SystemExit(1)

    # Fetch all user emails via admin client (bypasses RLS)
    response = admin.table("profiles").select("id,email").execute()
    users = response.data if response and response.data else []

    if not users:
        click.echo("No users found in the profiles table.")
        return

    click.echo(f"Found {len(users)} user(s) to notify.")

    if not confirm:
        click.echo("\nDry run — no emails sent. Use --confirm to send.")
        return

    # Send emails with progress tracking
    sent = 0
    failed = 0
    skipped = 0

    for i, user in enumerate(users, 1):
        email = user.get("email")
        if not email:
            skipped += 1
            continue

        result = send_legal_update_email(email)
        if result.get("success"):
            sent += 1
        elif result.get("error") == "rate_limit":
            click.echo(f"  [{i}/{len(users)}] Rate limited — waiting 2s...")
            time.sleep(2)
            # Retry once after waiting
            result = send_legal_update_email(email)
            if result.get("success"):
                sent += 1
            else:
                failed += 1
                click.echo(f"  [{i}/{len(users)}] Failed (after retry): {mask_email(email)}")
        else:
            failed += 1
            click.echo(f"  [{i}/{len(users)}] Failed: {result.get('error', 'unknown')}")

        # Brief pause between emails to avoid rate limits
        if i < len(users):
            time.sleep(0.5)

    click.echo(f"\nDone. Sent: {sent}, Failed: {failed}, Skipped: {skipped}")


@click.command("generate-og-images")
@click.option("--force", is_flag=True, default=False,
              help="Regenerate all images even if they already exist.")
@with_appcontext
def generate_og_images_command(force: bool) -> None:
    """Generate OG preview images (1200x630) for all content pages."""
    from pathlib import Path

    from app.services.og_image import generate_og_image
    from app.utils.data import load_data_file

    output_dir = Path(__file__).parent / "static" / "images" / "og"

    pages: list[dict[str, str]] = []

    # Plant care guides
    for guide in load_data_file("guides.json"):
        pages.append({
            "filename": f"guide-{guide['slug']}.png",
            "title": f"{guide['name']} Care Guide",
            "emoji": guide["emoji"],
        })

    # SEO landing pages
    for page in load_data_file("seo_landing_pages.json"):
        pages.append({
            "filename": f"seo-{page['slug']}.png",
            "title": page["title"],
            "emoji": page["emoji"],
        })

    # SEO hub pages
    for page in load_data_file("seo_hub_pages.json"):
        pages.append({
            "filename": f"hub-{page['slug']}.png",
            "title": page["title"],
            "emoji": page["emoji"],
        })

    # Static pages
    pages.extend([
        {"filename": "home.png", "title": "AI-Powered Plant Care Assistant", "emoji": "🌿"},
        {"filename": "features.png", "title": "Features & Pricing", "emoji": "✨"},
        {"filename": "ask.png", "title": "Ask the AI Plant Assistant", "emoji": "🤖"},
        {"filename": "plant-doctor.png", "title": "AI Plant Doctor", "emoji": "🩺"},
        {"filename": "guides-index.png", "title": "Plant Care Guides", "emoji": "📚"},
    ])

    generated = 0
    skipped = 0
    failed = 0

    for page_info in pages:
        # Sanitize filename to prevent path traversal
        safe_name = Path(page_info["filename"]).name
        out = output_dir / safe_name
        if out.exists() and not force:
            skipped += 1
            continue

        try:
            generate_og_image(
                title=page_info["title"],
                emoji=page_info["emoji"],
                output_path=out,
            )
            generated += 1
            click.echo(f"  Generated: {safe_name}")
        except Exception as e:
            failed += 1
            click.echo(f"  FAILED: {safe_name} ({e})")

    click.echo(f"\nDone. Generated: {generated}, Failed: {failed}, Skipped (exists): {skipped}")
    click.echo(f"Output: {output_dir}")
