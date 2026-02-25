"""
OG image generator for social sharing previews.

Generates branded 1200x630 PNG images with page title, emoji, leaf logo, and
PlantCareAI branding. Uses Pillow (already in requirements.txt).

Usage:
    from app.services.og_image import generate_og_image
    generate_og_image(title="Why Are My Leaves Drooping?", emoji="🥀", output_path="out.png")
"""

from __future__ import annotations

import logging
import os
import platform
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Dimensions
WIDTH = 1200
HEIGHT = 630

# Brand colors (matching Tailwind config)
NAVY = (15, 23, 42)  # slate-900 / #0f172a
EMERALD = (16, 185, 129)  # emerald-500 / #10b981
LIME = (132, 204, 22)  # lime-500 / #84cc16
WHITE = (255, 255, 255)

FONTS_DIR = Path(__file__).parent.parent / "static" / "fonts"
IMAGES_DIR = Path(__file__).parent.parent / "static" / "images"
LEAF_LOGO_PATH = IMAGES_DIR / "icons" / "custom-leaf.png"

# Module-level caches (loaded once, reused across generate_og_image calls)
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_emoji_font_cache: dict[int, ImageFont.FreeTypeFont] = {}
_logo_cache: dict[int, Image.Image | None] = {}


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled font file with caching, falling back to default if missing."""
    key = (name, size)
    if key not in _font_cache:
        font_path = FONTS_DIR / name
        try:
            _font_cache[key] = ImageFont.truetype(str(font_path), size)
        except (OSError, IOError):
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def _load_emoji_font(size: int) -> ImageFont.FreeTypeFont:
    """Load a system emoji font with caching. Warns if no emoji font is found."""
    if size in _emoji_font_cache:
        return _emoji_font_cache[size]

    candidates: list[str] = []
    if platform.system() == "Windows":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        candidates.append(os.path.join(windir, "Fonts", "seguiemj.ttf"))
    candidates.extend([
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",  # Linux (Debian/Ubuntu)
        "/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf",     # Linux (Fedora)
        "/System/Library/Fonts/Apple Color Emoji.ttc",         # macOS
    ])
    # Also try bundled emoji font in static/fonts/
    candidates.append(str(FONTS_DIR / "NotoColorEmoji.ttf"))
    for path in candidates:
        try:
            font = ImageFont.truetype(path, size)
            _emoji_font_cache[size] = font
            return font
        except (OSError, IOError):
            continue

    logger.warning("No emoji font found — emoji will not render correctly in OG images")
    fallback = _load_font("Inter-Bold.ttf", size)
    _emoji_font_cache[size] = fallback
    return fallback


def _load_leaf_logo(target_height: int) -> Image.Image | None:
    """Load and resize the PlantCareAI leaf logo with caching."""
    if target_height not in _logo_cache:
        try:
            logo = Image.open(str(LEAF_LOGO_PATH)).convert("RGBA")
            aspect = logo.width / logo.height
            new_w = int(target_height * aspect)
            _logo_cache[target_height] = logo.resize(
                (new_w, target_height), Image.Resampling.LANCZOS
            )
        except (OSError, IOError):
            _logo_cache[target_height] = None
    return _logo_cache[target_height]


def generate_og_image(
    title: str,
    emoji: str,
    output_path: str | Path,
) -> Path:
    """Generate a 1200x630 OG image with branding.

    Layout:
    - Dark navy background with emerald accent bars
    - Leaf logo (bottom-right, subtle watermark at 15% opacity)
    - Emoji centered above title
    - Page title centered, word-wrapped
    - "PlantCareAI" brand name + "plantcareai.app" URL at bottom

    Returns the output path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGBA", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(img)

    # Top and bottom accent bars
    draw.rectangle([0, 0, WIDTH, 4], fill=EMERALD)
    draw.rectangle([0, HEIGHT - 4, WIDTH, HEIGHT], fill=EMERALD)

    # Leaf logo as subtle watermark (bottom-right corner)
    logo_src = _load_leaf_logo(target_height=280)
    if logo_src:
        # Copy so we don't mutate the cached version
        logo = logo_src.copy()
        r, g, b, a = logo.split()
        a = a.point(lambda x: int(x * 0.15))
        logo = Image.merge("RGBA", (r, g, b, a))
        logo_x = WIDTH - logo.width - 40
        logo_y = HEIGHT - logo.height - 20
        img.paste(logo, (logo_x, logo_y), logo)
        # Redraw bottom accent bar over logo area
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, HEIGHT - 4, WIDTH, HEIGHT], fill=EMERALD)

    # Load fonts
    font_emoji = _load_emoji_font(72)
    font_title = _load_font("Inter-Bold.ttf", 48)
    font_brand = _load_font("Inter-Bold.ttf", 24)
    font_url = _load_font("Inter-Regular.ttf", 20)

    # --- Layout: vertically centered content block ---
    # Emoji at top, title in middle, brand at bottom
    # Shift everything down ~40px from old layout for better vertical balance

    # Draw emoji (centered)
    emoji_bbox = draw.textbbox((0, 0), emoji, font=font_emoji)
    emoji_w = emoji_bbox[2] - emoji_bbox[0]
    draw.text(((WIDTH - emoji_w) / 2, 150), emoji, font=font_emoji, fill=WHITE)

    # Draw title (centered, word-wrapped)
    wrapped = textwrap.fill(title, width=35)
    lines = wrapped.split("\n")

    line_height = 60
    total_text_height = len(lines) * line_height
    y_start = 330 - (total_text_height / 2)

    for i, line in enumerate(lines):
        line_bbox = draw.textbbox((0, 0), line, font=font_title)
        line_w = line_bbox[2] - line_bbox[0]
        y = y_start + (i * line_height)
        draw.text(((WIDTH - line_w) / 2, y), line, font=font_title, fill=WHITE)

    # Brand name "PlantCareAI" centered above URL
    brand_name = "PlantCareAI"
    brand_bbox = draw.textbbox((0, 0), brand_name, font=font_brand)
    brand_w = brand_bbox[2] - brand_bbox[0]
    draw.text(
        ((WIDTH - brand_w) / 2, HEIGHT - 80),
        brand_name,
        font=font_brand,
        fill=EMERALD,
    )

    # URL "plantcareai.app" below brand name
    url_text = "plantcareai.app"
    url_bbox = draw.textbbox((0, 0), url_text, font=font_url)
    url_w = url_bbox[2] - url_bbox[0]
    draw.text(
        ((WIDTH - url_w) / 2, HEIGHT - 52),
        url_text,
        font=font_url,
        fill=LIME,
    )

    # Convert to RGB for PNG output (no alpha channel needed in final image)
    final = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    final.paste(img, mask=img.split()[3])
    final.save(str(output_path), "PNG", optimize=True)
    return output_path
