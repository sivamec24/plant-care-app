"""
Plant Intelligence Service - AI-powered plant characteristic inference.

Uses AI to infer plant characteristics (origin, lifecycle, cold tolerance, water needs)
from species, location, and user notes without requiring new database fields.

Features:
- AI-powered characteristic inference
- Caching layer to avoid repeated API calls (1 week cache)
- Light-based watering adjustment factors
- Graceful fallback to defaults when AI unavailable
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
import json
import hashlib
from flask import current_app, has_app_context

from .weather import infer_hardiness_zone


# In-memory cache for AI inference results (production should use Redis/Memcached)
_INFERENCE_CACHE: Dict[str, Dict[str, Any]] = {}


def _get_cache_key(plant_data: Dict[str, Any]) -> str:
    """
    Generate cache key from plant data.

    Args:
        plant_data: Plant dictionary with species, location, notes

    Returns:
        MD5 hash of key plant attributes
    """
    # Build stable string from key attributes
    key_parts = [
        plant_data.get("species", ""),
        plant_data.get("location", ""),
        plant_data.get("notes", "")[:200],  # First 200 chars of notes
        plant_data.get("light", ""),
    ]
    key_string = "|".join(str(p) for p in key_parts)

    # Hash to fixed length
    return hashlib.md5(key_string.encode(), usedforsecurity=False).hexdigest()


def _get_cached_inference(cache_key: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve cached inference if available and not expired.

    Args:
        cache_key: Cache key from _get_cache_key()

    Returns:
        Cached inference dict or None if expired/missing
    """
    if cache_key not in _INFERENCE_CACHE:
        return None

    cached = _INFERENCE_CACHE[cache_key]
    cached_at = cached.get("cached_at")

    if not cached_at:
        return None

    # Check if cache expired (1 week = 168 hours)
    cache_hours = 168
    if has_app_context():
        from app.config import BaseConfig
        cache_hours = getattr(BaseConfig, "WEATHER_AI_INFERENCE_CACHE_HOURS", 168)

    now = datetime.now(timezone.utc)
    if isinstance(cached_at, str):
        cached_at = datetime.fromisoformat(cached_at)

    # Make timezone-aware if naive
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)

    age_hours = (now - cached_at).total_seconds() / 3600

    if age_hours > cache_hours:
        # Expired
        del _INFERENCE_CACHE[cache_key]
        return None

    return cached.get("inference")


def _cache_inference(cache_key: str, inference: Dict[str, Any]) -> None:
    """
    Cache inference result with timestamp.

    Args:
        cache_key: Cache key from _get_cache_key()
        inference: Inference result to cache
    """
    _INFERENCE_CACHE[cache_key] = {
        "inference": inference,
        "cached_at": datetime.now(timezone.utc)
    }


def _infer_with_ai(
    plant_species: str,
    plant_location: str,
    plant_notes: Optional[str],
    user_city: Optional[str],
    hardiness_zone: Optional[str]
) -> Optional[Dict[str, Any]]:
    """
    Use AI to infer plant characteristics.

    Args:
        plant_species: Species or common name
        plant_location: indoor_potted, outdoor_potted, outdoor_bed
        plant_notes: User notes about the plant
        user_city: User's city for climate context
        hardiness_zone: USDA hardiness zone

    Returns:
        Dict with inferred characteristics or None on failure:
        {
            "origin": "native|non_native_adapted|non_native_not_adapted",
            "lifecycle": "annual|biennial|perennial|unknown",
            "cold_tolerance": "hardy|semi_hardy|tender",
            "water_needs": "low|moderate|high",
            "dormancy_months": [11, 12, 1, 2],  # Months when plant is dormant
            "confidence": 0.85
        }
    """
    try:
        from .ai import _get_litellm_router

        router, err = _get_litellm_router()
        if not router:
            return None

        # Build prompt for characteristic inference
        system_prompt = (
            "You are a botanical expert. Analyze the plant information provided and infer key characteristics. "
            "Respond ONLY with valid JSON in this exact format:\n"
            "{\n"
            '  "origin": "native|non_native_adapted|non_native_not_adapted",\n'
            '  "lifecycle": "annual|biennial|perennial|unknown",\n'
            '  "cold_tolerance": "hardy|semi_hardy|tender",\n'
            '  "water_needs": "low|moderate|high",\n'
            '  "dormancy_months": [11, 12, 1, 2],\n'
            '  "confidence": 0.85\n'
            "}\n\n"
            "Definitions:\n"
            "- origin: Whether plant is native to the region, non-native but adapted, or non-native and not adapted\n"
            "- lifecycle: Annual (1 year), biennial (2 years), perennial (multi-year), or unknown\n"
            "- cold_tolerance: hardy (<-20F), semi_hardy (0-20F), tender (>32F)\n"
            "- water_needs: low (drought-tolerant), moderate (regular), high (frequent watering)\n"
            "- dormancy_months: List of month numbers (1-12) when plant is dormant/inactive\n"
            "- confidence: 0-1 score of inference confidence\n\n"
            "Base your inference on botanical knowledge of the species and climate context."
        )

        user_prompt_parts = [f"Plant species: {plant_species}"]

        if plant_location:
            user_prompt_parts.append(f"Location: {plant_location}")

        if user_city:
            user_prompt_parts.append(f"City: {user_city}")

        if hardiness_zone:
            user_prompt_parts.append(f"USDA Hardiness Zone: {hardiness_zone}")

        if plant_notes:
            # Truncate notes to 200 chars
            notes_truncated = plant_notes[:200]
            user_prompt_parts.append(f"User notes: {notes_truncated}")

        user_prompt = "\n".join(user_prompt_parts)

        # Determine model to use
        import os
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key and has_app_context():
            openai_key = current_app.config.get("OPENAI_API_KEY")

        model_to_use = "primary-gpt" if openai_key else "fallback-gemini"

        # Call AI
        resp = router.completion(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,  # Lower temperature for more consistent inference
            max_tokens=300
        )

        response_text = (resp.choices[0].message.content or "").strip()

        # Parse JSON response
        # Sometimes AI wraps JSON in markdown code blocks
        if response_text.startswith("```"):
            # Extract JSON from code block
            lines = response_text.split("\n")
            json_lines = []
            in_code_block = False
            for line in lines:
                if line.startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    json_lines.append(line)
            response_text = "\n".join(json_lines)

        inference = json.loads(response_text)

        # Validate required fields
        required_fields = ["origin", "lifecycle", "cold_tolerance", "water_needs", "dormancy_months", "confidence"]
        if not all(field in inference for field in required_fields):
            return None

        # Validate enums
        valid_origins = ["native", "non_native_adapted", "non_native_not_adapted"]
        valid_lifecycles = ["annual", "biennial", "perennial", "unknown"]
        valid_tolerances = ["hardy", "semi_hardy", "tender"]
        valid_water_needs = ["low", "moderate", "high"]

        if inference["origin"] not in valid_origins:
            inference["origin"] = "non_native_adapted"  # Safe default

        if inference["lifecycle"] not in valid_lifecycles:
            inference["lifecycle"] = "unknown"

        if inference["cold_tolerance"] not in valid_tolerances:
            inference["cold_tolerance"] = "semi_hardy"  # Safe default

        if inference["water_needs"] not in valid_water_needs:
            inference["water_needs"] = "moderate"  # Safe default

        # Validate dormancy_months is list of integers 1-12
        if not isinstance(inference["dormancy_months"], list):
            inference["dormancy_months"] = []
        else:
            inference["dormancy_months"] = [
                m for m in inference["dormancy_months"]
                if isinstance(m, int) and 1 <= m <= 12
            ]

        # Validate confidence is float 0-1
        try:
            confidence = float(inference["confidence"])
            inference["confidence"] = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            inference["confidence"] = 0.5  # Default medium confidence

        return inference

    except Exception as e:
        # Log error if in app context
        if has_app_context():
            from app.utils.errors import log_info
            log_info(f"AI plant inference failed: {str(e)}")
        return None


def _get_default_inference(plant_location: str) -> Dict[str, Any]:
    """
    Return default inference when AI unavailable.

    Args:
        plant_location: indoor_potted, outdoor_potted, outdoor_bed

    Returns:
        Conservative default characteristics
    """
    # Conservative defaults
    return {
        "origin": "non_native_adapted",
        "lifecycle": "unknown",
        "cold_tolerance": "semi_hardy",
        "water_needs": "moderate",
        "dormancy_months": [],  # No dormancy assumed
        "confidence": 0.3,  # Low confidence for defaults
        "source": "default"  # Indicate this is a fallback
    }


def infer_plant_characteristics(
    plant: Dict[str, Any],
    user_city: Optional[str] = None
) -> Dict[str, Any]:
    """
    Infer plant characteristics using AI with caching.

    Uses AI to analyze plant species, location, and notes to infer:
    - Origin (native, non-native adapted, non-native not adapted)
    - Lifecycle (annual, biennial, perennial)
    - Cold tolerance (hardy, semi-hardy, tender)
    - Water needs (low, moderate, high)
    - Dormancy months (when plant is dormant)

    Results are cached for 1 week to avoid repeated API calls.
    Falls back to conservative defaults if AI unavailable.

    Args:
        plant: Plant dict with species, location, notes, etc.
        user_city: Optional user city for climate context

    Returns:
        Dict with inferred characteristics:
        {
            "origin": "native|non_native_adapted|non_native_not_adapted",
            "lifecycle": "annual|biennial|perennial|unknown",
            "cold_tolerance": "hardy|semi_hardy|tender",
            "water_needs": "low|moderate|high",
            "dormancy_months": [11, 12, 1, 2],
            "confidence": 0.85,
            "source": "ai|cache|default"
        }

    Example:
        >>> plant = {"species": "Monstera deliciosa", "location": "indoor_potted", "notes": "Tropical plant"}
        >>> inference = infer_plant_characteristics(plant, "Seattle, WA")
        >>> print(inference["water_needs"])
        'moderate'
    """
    # Check cache first
    cache_key = _get_cache_key(plant)
    cached = _get_cached_inference(cache_key)

    if cached:
        cached["source"] = "cache"
        return cached

    # Get species and location
    species = plant.get("species") or plant.get("name") or "Unknown plant"
    location = plant.get("location", "indoor_potted")
    notes = plant.get("notes")

    # Infer hardiness zone if city provided
    hardiness_zone = None
    if user_city:
        hardiness_zone = infer_hardiness_zone(user_city)

    # Check if AI inference enabled
    ai_enabled = True
    if has_app_context():
        from app.config import BaseConfig
        ai_enabled = getattr(BaseConfig, "WEATHER_AI_INFERENCE_ENABLED", True)

    if not ai_enabled:
        return _get_default_inference(location)

    # Try AI inference
    inference = _infer_with_ai(species, location, notes, user_city, hardiness_zone)

    if inference:
        inference["source"] = "ai"
        # Cache successful inference
        _cache_inference(cache_key, inference)
        return inference

    # Fallback to defaults
    return _get_default_inference(location)


def get_light_adjustment_factor(
    plant: Dict[str, Any],
    weather: Optional[Dict[str, Any]] = None,
    seasonal_pattern: Optional[Dict[str, Any]] = None
) -> float:
    """
    Calculate light-based watering adjustment factor.

    Different light conditions affect evapotranspiration rates:
    - Indoor artificial light: No seasonal adjustment (1.0x year-round)
    - Indoor natural light: Seasonal adjustment based on day length
    - Outdoor full sun: Higher water needs (1.2-1.3x in summer)
    - Outdoor partial sun: Moderate needs (1.0-1.1x)
    - Outdoor shade: Lower water needs (0.7-0.8x)

    Args:
        plant: Plant dict with location and light fields
        weather: Optional weather dict for seasonal context
        seasonal_pattern: Optional seasonal pattern from get_seasonal_pattern()

    Returns:
        Multiplier for watering frequency (0.7 - 1.3)

    Example:
        >>> plant = {"location": "outdoor_potted", "light": "full_sun"}
        >>> seasonal = {"season": "summer", "is_dormancy_period": False}
        >>> factor = get_light_adjustment_factor(plant, seasonal_pattern=seasonal)
        >>> print(factor)
        1.3
    """
    location = plant.get("location") or "indoor_potted"
    light = plant.get("light") or "bright_indirect"

    # INDOOR PLANTS
    if "indoor" in location.lower():
        # Check if using artificial light (from notes)
        notes = (plant.get("notes") or "").lower()
        uses_grow_light = any(term in notes for term in ["grow light", "led light", "artificial light", "lamp"])

        if uses_grow_light:
            # Artificial light = consistent year-round
            return 1.0

        # Natural indoor light = seasonal variation
        season = None
        if seasonal_pattern:
            season = seasonal_pattern.get("season")
        elif weather:
            # Infer from temperature if no seasonal pattern
            temp_f = weather.get("temp_f")
            if temp_f:
                if temp_f > 75:
                    season = "summer"
                elif temp_f > 60:
                    season = "spring"
                elif temp_f > 45:
                    season = "fall"
                else:
                    season = "winter"

        # Adjust based on season
        if season == "summer":
            return 1.1  # More light = more water
        elif season == "winter":
            return 0.9  # Less light = less water
        else:
            return 1.0  # Spring/fall = baseline

    # OUTDOOR PLANTS
    # Parse light level
    light_lower = light.lower()

    # Get season
    season = "spring"  # Default
    if seasonal_pattern:
        season = seasonal_pattern.get("season", "spring")
    elif weather:
        temp_f = weather.get("temp_f")
        if temp_f:
            if temp_f > 75:
                season = "summer"
            elif temp_f > 60:
                season = "spring"
            elif temp_f > 45:
                season = "fall"
            else:
                season = "winter"

    # Check for dormancy
    is_dormant = False
    if seasonal_pattern:
        is_dormant = seasonal_pattern.get("is_dormancy_period", False)

    if is_dormant:
        # Dormant plants need much less water
        return 0.6

    # Full sun plants
    if "full" in light_lower and "sun" in light_lower:
        if season == "summer":
            return 1.3  # High evaporation
        elif season == "spring" or season == "fall":
            return 1.1
        else:
            return 0.9  # Winter, less intense

    # Partial sun / partial shade
    if "partial" in light_lower:
        if season == "summer":
            return 1.1
        else:
            return 1.0

    # Shade plants
    if "shade" in light_lower:
        if season == "summer":
            return 0.8
        else:
            return 0.7  # Much less water needed

    # Default moderate light
    return 1.0


def clear_inference_cache():
    """
    Clear the AI inference cache.

    Useful for:
    - Testing
    - Manual cache invalidation
    - Memory management
    """
    global _INFERENCE_CACHE
    _INFERENCE_CACHE = {}
