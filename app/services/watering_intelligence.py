"""
Watering Intelligence Service - Stress-based watering recommendations.

Analyzes weather, plant care history, and environmental factors to provide
intelligent watering recommendations adapted from Universal Watering Logic.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def check_watering_eligibility(
    hours_since_watered: Optional[float],
    recent_rain: bool = False,
    rain_expected: bool = False,
    in_skip_window: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Check if watering is eligible based on timing and rain conditions.

    Args:
        hours_since_watered: Hours since last watering (None if never watered)
        recent_rain: Whether ≥0.25" rain in past 48 hours
        rain_expected: Whether ≥0.25" rain expected today/tonight
        in_skip_window: Whether in 48-hour post-rain skip window

    Returns:
        (is_eligible, reason_if_not_eligible)
    """
    # First watering always eligible
    if hours_since_watered is None:
        return True, None

    # Check 48-hour minimum between waterings
    if hours_since_watered < 48:
        hours_remaining = 48 - hours_since_watered
        return False, f"Last watered {hours_since_watered:.1f}h ago (wait {hours_remaining:.1f}h more)"

    # Check rain conditions
    if recent_rain:
        return False, "Recent rain (≥0.25\" in past 48h)"

    if rain_expected:
        return False, "Rain expected today/tonight"

    if in_skip_window:
        return False, "In post-rain skip window"

    return True, None


def calculate_stress_score(
    weather: Dict[str, Any],
    hours_since_rain: Optional[float] = None,
    plant_type: str = "houseplant",
    plant_age_weeks: Optional[int] = None
) -> Dict[str, Any]:
    """
    Calculate environmental stress score for watering decisions.

    Adapted from Universal Watering Logic for houseplants and outdoor plants.

    Args:
        weather: Weather dict with temp_f, humidity, wind_mph, conditions, dewpoint
        hours_since_rain: Hours since last ≥0.25" rain (for outdoor plants)
        plant_type: "houseplant", "outdoor_shrub", "outdoor_wildflower"
        plant_age_weeks: Plant age in weeks (for germination adjustments)

    Returns:
        {
            "total_score": int,
            "factors": List[str],  # Contributing stress factors
            "breakdown": Dict[str, int]  # Score breakdown by category
        }
    """
    score = 0
    factors = []
    breakdown = {
        "heat": 0,
        "wind": 0,
        "dry_spell": 0,
        "air_dryness": 0,
        "sun_et": 0
    }

    temp_f = weather.get("temp_f", 70)
    humidity = weather.get("humidity", 50)
    wind_mph = weather.get("wind_mph", 0)
    dewpoint = weather.get("dewpoint", 50)
    conditions = (weather.get("conditions") or "").lower()

    is_clear = any(word in conditions for word in ["clear", "sunny"])
    is_wildflower = plant_type == "outdoor_wildflower"
    is_germination = is_wildflower and plant_age_weeks and plant_age_weeks <= 4

    # HEAT STRESS
    if temp_f >= 92:
        heat_points = 4 if is_wildflower else 3
        score += heat_points
        breakdown["heat"] = heat_points
        factors.append(f"very hot ({temp_f}°F)")
    elif temp_f >= 88:
        heat_points = 3 if is_wildflower else 2
        score += heat_points
        breakdown["heat"] = heat_points
        factors.append(f"hot ({temp_f}°F)")
    elif temp_f >= 82:
        heat_points = 1
        score += heat_points
        breakdown["heat"] = heat_points
        factors.append(f"warm ({temp_f}°F)")

    # WIND STRESS (primarily for outdoor plants)
    if plant_type.startswith("outdoor"):
        if wind_mph > 30:
            wind_points = 3
            score += wind_points
            breakdown["wind"] = wind_points
            factors.append(f"very windy ({wind_mph}mph)")
        elif wind_mph >= 25:
            wind_points = 2
            score += wind_points
            breakdown["wind"] = wind_points
            factors.append(f"windy ({wind_mph}mph)")
        elif wind_mph >= 20:
            wind_points = 1
            score += wind_points
            breakdown["wind"] = wind_points
            factors.append(f"breezy ({wind_mph}mph)")

        # Extra wind sensitivity during germination
        if is_germination and wind_mph > 15:
            score += 1
            breakdown["wind"] += 1
            factors.append("germination + wind")

    # DRY-SPELL (for outdoor plants with rain tracking)
    if plant_type.startswith("outdoor") and hours_since_rain is not None:
        if hours_since_rain >= 240:  # 10 days
            dry_points = 3
            score += dry_points
            breakdown["dry_spell"] = dry_points
            factors.append(f"long dry spell ({hours_since_rain//24:.0f}d no rain)")
        elif hours_since_rain >= 168:  # 7 days
            dry_points = 2
            score += dry_points
            breakdown["dry_spell"] = dry_points
            factors.append(f"dry spell ({hours_since_rain//24:.0f}d no rain)")
        elif hours_since_rain >= 120:  # 5 days
            dry_points = 1
            score += dry_points
            breakdown["dry_spell"] = dry_points
            factors.append(f"no recent rain ({hours_since_rain//24:.0f}d)")

    # AIR DRYNESS
    if dewpoint < 35:
        dry_points = 2
        score += dry_points
        breakdown["air_dryness"] = dry_points
        factors.append(f"very dry air (dewpoint {dewpoint}°F)")
    elif dewpoint < 45:
        dry_points = 1
        score += dry_points
        breakdown["air_dryness"] = dry_points
        factors.append(f"dry air (dewpoint {dewpoint}°F)")

    if humidity < 15:
        dry_points = 2
        score += dry_points
        breakdown["air_dryness"] += dry_points
        factors.append(f"extremely low humidity ({humidity}%)")
    elif humidity < 25:
        dry_points = 1
        score += dry_points
        breakdown["air_dryness"] += dry_points
        factors.append(f"low humidity ({humidity}%)")

    # SUN / EVAPOTRANSPIRATION BOOST
    if is_clear:
        if temp_f >= 92:
            et_points = 3
            score += et_points
            breakdown["sun_et"] = et_points
            factors.append("intense sun + heat")
        elif temp_f >= 88:
            et_points = 2
            score += et_points
            breakdown["sun_et"] = et_points
            factors.append("strong sun + heat")
        elif temp_f >= 82:
            et_points = 1
            score += et_points
            breakdown["sun_et"] = et_points
            factors.append("sunny + warm")

        # Extra ET sensitivity during germination
        if is_germination:
            score += 1
            breakdown["sun_et"] += 1
            factors.append("germination + sun exposure")

    return {
        "total_score": score,
        "factors": factors,
        "breakdown": breakdown
    }


def determine_watering_recommendation(
    stress_score: int,
    plant_type: str = "houseplant",
    plant_age_weeks: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Determine whether to water based on stress score and plant type.

    Args:
        stress_score: Total environmental stress score
        plant_type: "houseplant", "outdoor_shrub", "outdoor_wildflower"
        plant_age_weeks: Plant age in weeks (for wildflowers)

    Returns:
        (should_water, threshold_explanation)
    """
    if plant_type == "outdoor_wildflower":
        if plant_age_weeks and plant_age_weeks <= 3:
            # Germination phase: water if score ≥ 2
            should_water = stress_score >= 2
            threshold = 2
        else:
            # Established: water if score ≥ 3
            should_water = stress_score >= 3
            threshold = 3
        explanation = f"wildflower threshold: {threshold}"
    elif plant_type == "outdoor_shrub":
        # Shrubs: water if score ≥ 2
        should_water = stress_score >= 2
        threshold = 2
        explanation = f"shrub threshold: {threshold}"
    else:
        # Houseplants: conservative threshold of ≥ 2
        should_water = stress_score >= 2
        threshold = 2
        explanation = f"houseplant threshold: {threshold}"

    return should_water, explanation


def generate_watering_recommendation(
    plant_name: str,
    hours_since_watered: Optional[float],
    weather: Optional[Dict[str, Any]],
    plant_type: str = "houseplant",
    plant_age_weeks: Optional[int] = None,
    hours_since_rain: Optional[float] = None,
    recent_rain: bool = False,
    rain_expected: bool = False
) -> Dict[str, Any]:
    """
    Generate complete watering recommendation for a plant.

    This is the main entry point for watering intelligence.

    Args:
        plant_name: Plant's display name
        hours_since_watered: Hours since last watering (None if never watered)
        weather: Current weather data
        plant_type: "houseplant", "outdoor_shrub", "outdoor_wildflower"
        plant_age_weeks: Plant age in weeks (for wildflowers)
        hours_since_rain: Hours since last ≥0.25" rain (for outdoor plants)
        recent_rain: Whether ≥0.25" rain in past 48 hours
        rain_expected: Whether ≥0.25" rain expected today/tonight

    Returns:
        {
            "should_water": bool,
            "recommendation": str,  # Human-readable recommendation
            "reason": str,  # Brief explanation
            "stress_score": int,
            "stress_factors": List[str],
            "eligible": bool,
            "eligibility_reason": Optional[str]
        }
    """
    # Check eligibility first
    is_eligible, eligibility_reason = check_watering_eligibility(
        hours_since_watered=hours_since_watered,
        recent_rain=recent_rain,
        rain_expected=rain_expected,
        in_skip_window=False  # TODO: Implement skip window tracking
    )

    if not is_eligible:
        return {
            "should_water": False,
            "recommendation": f"💧 {plant_name}: NOT YET",
            "reason": eligibility_reason,
            "stress_score": 0,
            "stress_factors": [],
            "eligible": False,
            "eligibility_reason": eligibility_reason
        }

    # Calculate stress score (only if eligible)
    if not weather:
        # No weather data - fall back to simple time-based recommendation
        if hours_since_watered is None:
            return {
                "should_water": True,
                "recommendation": f"💧 {plant_name}: CHECK SOIL",
                "reason": "Never watered - check soil moisture",
                "stress_score": 0,
                "stress_factors": ["no watering history"],
                "eligible": True,
                "eligibility_reason": None
            }
        elif hours_since_watered >= 168:  # 7 days
            return {
                "should_water": True,
                "recommendation": f"💧 {plant_name}: LIKELY YES",
                "reason": f"Last watered {hours_since_watered//24:.0f} days ago",
                "stress_score": 0,
                "stress_factors": ["long time since watering"],
                "eligible": True,
                "eligibility_reason": None
            }
        else:
            return {
                "should_water": False,
                "recommendation": f"💧 {plant_name}: PROBABLY NOT",
                "reason": f"Watered {hours_since_watered//24:.0f} days ago - check soil",
                "stress_score": 0,
                "stress_factors": [],
                "eligible": True,
                "eligibility_reason": None
            }

    # Calculate stress with weather data
    stress_result = calculate_stress_score(
        weather=weather,
        hours_since_rain=hours_since_rain,
        plant_type=plant_type,
        plant_age_weeks=plant_age_weeks
    )

    stress_score = stress_result["total_score"]
    stress_factors = stress_result["factors"]

    # Determine recommendation
    should_water, threshold_explanation = determine_watering_recommendation(
        stress_score=stress_score,
        plant_type=plant_type,
        plant_age_weeks=plant_age_weeks
    )

    # Build recommendation text
    if should_water:
        top_factors = stress_factors[:2] if len(stress_factors) >= 2 else stress_factors
        factors_text = ", ".join(top_factors) if top_factors else "multiple factors"
        recommendation = f"💧 {plant_name}: YES — {factors_text}"
        reason = f"Stress score {stress_score} (threshold met: {threshold_explanation})"
    else:
        recommendation = f"💧 {plant_name}: NOT YET"
        if stress_score == 0:
            reason = "Favorable conditions - no stress detected"
        else:
            reason = f"Stress score {stress_score} (below threshold: {threshold_explanation})"

    return {
        "should_water": should_water,
        "recommendation": recommendation,
        "reason": reason,
        "stress_score": stress_score,
        "stress_factors": stress_factors,
        "eligible": True,
        "eligibility_reason": None
    }


def get_watering_instructions(
    plant_type: str = "houseplant",
    weather: Optional[Dict[str, Any]] = None
) -> str:
    """
    Get watering instruction guidance based on plant type and weather.

    Args:
        plant_type: "houseplant", "outdoor_shrub", "outdoor_wildflower"
        weather: Current weather data (for outdoor adjustments)

    Returns:
        Human-readable watering instructions
    """
    if plant_type == "houseplant":
        return "Water thoroughly until drainage, then allow top 1-2\" to dry before next watering."

    if plant_type == "outdoor_wildflower":
        base = "AM: 5-10 min fine soak at soil level. PM: 2-5 min only if windy/hot."
        if weather:
            wind_mph = weather.get("wind_mph", 0)
            dewpoint = weather.get("dewpoint", 50)

            if wind_mph >= 12:
                base += " PM mulch check & 2-3 min root-zone top-off recommended."

            if dewpoint >= 65:
                base += " Check for 'pinched' seedlings; let surface dry between waterings."
        return base

    if plant_type == "outdoor_shrub":
        return "Deep soak: ¾-1\" water penetration (~1-2 gal per plant). Focus on root zone, not foliage."

    return "Water at soil level until moisture penetrates root zone."
