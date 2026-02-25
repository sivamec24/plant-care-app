"""
SEO content pages for high-intent plant care searches.

Landing pages target specific pain points ("why are my plant leaves drooping").
Hub pages are pillar content linking to related landing pages (spoke pages).

Each page:
- Addresses a specific user pain point
- Provides empathetic, helpful content
- Funnels to /ask for personalized AI advice
- Links to related pages for internal linking
"""

from __future__ import annotations
from flask import Blueprint, abort, render_template
from typing import Optional
from app.utils.data import load_data_file


seo_bp = Blueprint("seo", __name__)


# Load once at import time
LANDING_PAGES = {page["slug"]: page for page in load_data_file("seo_landing_pages.json")}
HUB_PAGES = {page["slug"]: page for page in load_data_file("seo_hub_pages.json")}

# Slug to route name mapping for URL generation
SLUG_TO_ROUTE = {page["slug"]: page["route_name"] for page in LANDING_PAGES.values()}

# Reverse lookup: landing page slug → parent hub page (for breadcrumbs)
SPOKE_TO_HUB: dict[str, dict] = {}
for _hub in HUB_PAGES.values():
    for _spoke_slug in _hub.get("spoke_pages", []):
        SPOKE_TO_HUB[_spoke_slug] = _hub


def _get_page(slug: str) -> dict:
    """Get landing page data by slug, or abort 404."""
    page = LANDING_PAGES.get(slug)
    if page is None:
        abort(404)
    return page


def _get_hub_page(slug: str) -> dict:
    """Get hub page data by slug, or abort 404."""
    page = HUB_PAGES.get(slug)
    if page is None:
        abort(404)
    return page


def _get_related_pages(slugs: list[str]) -> list[dict]:
    """Get page data for related pages."""
    return [
        {
            "slug": slug,
            "title": LANDING_PAGES[slug]["title"],
            "route_name": LANDING_PAGES[slug]["route_name"],
        }
        for slug in slugs
        if slug in LANDING_PAGES
    ]


def _get_spoke_pages(slugs: list[str]) -> list[dict]:
    """Get landing page data for hub spoke links."""
    return [
        {
            "slug": slug,
            "title": LANDING_PAGES[slug]["title"],
            "route_name": LANDING_PAGES[slug]["route_name"],
            "emoji": LANDING_PAGES[slug]["emoji"],
        }
        for slug in slugs
        if slug in LANDING_PAGES
    ]


def _render_landing(slug: str):
    """Shared renderer for all landing pages — includes parent hub for breadcrumbs."""
    page = _get_page(slug)
    related = _get_related_pages(page["related_pages"])
    parent_hub = SPOKE_TO_HUB.get(slug)
    return render_template(
        "seo/landing.html", page=page, related_pages=related, parent_hub=parent_hub
    )


@seo_bp.route("/why-are-my-plant-leaves-drooping")
def drooping():
    """Why are my plant leaves drooping? landing page."""
    return _render_landing("why-are-my-plant-leaves-drooping")


@seo_bp.route("/am-i-overwatering-my-plant")
def overwatering():
    """Am I overwatering my plant? landing page."""
    return _render_landing("am-i-overwatering-my-plant")


@seo_bp.route("/how-often-should-i-water-my-plant")
def watering_frequency():
    """How often should I water my plant? landing page."""
    return _render_landing("how-often-should-i-water-my-plant")


@seo_bp.route("/why-are-my-plant-leaves-turning-yellow")
def yellow_leaves():
    """Why are my plant leaves turning yellow? landing page."""
    return _render_landing("why-are-my-plant-leaves-turning-yellow")


@seo_bp.route("/should-i-water-my-plant-today")
def water_today():
    """Should I water my plant today? landing page."""
    return _render_landing("should-i-water-my-plant-today")


@seo_bp.route("/why-is-my-plant-not-growing")
def not_growing():
    """Why is my plant not growing? landing page."""
    return _render_landing("why-is-my-plant-not-growing")


@seo_bp.route("/indoor-plant-care-for-beginners")
def beginners_guide():
    """Indoor plant care for beginners landing page."""
    return _render_landing("indoor-plant-care-for-beginners")


@seo_bp.route("/why-are-my-plant-leaves-curling")
def curling_leaves():
    """Why are my plant leaves curling? landing page."""
    return _render_landing("why-are-my-plant-leaves-curling")


@seo_bp.route("/how-to-get-rid-of-fungus-gnats")
def fungus_gnats():
    """How to get rid of fungus gnats landing page."""
    return _render_landing("how-to-get-rid-of-fungus-gnats")


@seo_bp.route("/why-are-my-plant-leaves-turning-brown")
def brown_leaves():
    """Why are my plant leaves turning brown? landing page."""
    return _render_landing("why-are-my-plant-leaves-turning-brown")


@seo_bp.route("/how-to-treat-root-rot")
def root_rot():
    """How to treat root rot landing page."""
    return _render_landing("how-to-treat-root-rot")


# --- Hub (Pillar) Pages ---


@seo_bp.route("/plant-watering-guide")
def watering_hub():
    """Complete guide to watering houseplants — hub page."""
    page = _get_hub_page("plant-watering-guide")
    spoke_pages = _get_spoke_pages(page["spoke_pages"])
    return render_template("seo/hub.html", page=page, spoke_pages=spoke_pages)


@seo_bp.route("/plant-leaf-problems")
def leaf_problems_hub():
    """Plant leaf problems diagnosis & treatment — hub page."""
    page = _get_hub_page("plant-leaf-problems")
    spoke_pages = _get_spoke_pages(page["spoke_pages"])
    return render_template("seo/hub.html", page=page, spoke_pages=spoke_pages)
