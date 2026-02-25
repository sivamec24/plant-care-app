"""
Seasonal context service for AI personalization.

Provides proactive tips based on date, location, and weather conditions
to enrich AI responses even for users without plant data.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any


def get_current_season(latitude: float = 40.0) -> str:
    """
    Determine current season based on date and hemisphere.

    Args:
        latitude: User's latitude (positive = Northern, negative = Southern)

    Returns:
        Season name: 'winter', 'spring', 'summer', 'fall'
    """
    month = datetime.now().month

    # Northern Hemisphere seasons
    if month in (12, 1, 2):
        northern_season = "winter"
    elif month in (3, 4, 5):
        northern_season = "spring"
    elif month in (6, 7, 8):
        northern_season = "summer"
    else:  # 9, 10, 11
        northern_season = "fall"

    # Flip for Southern Hemisphere
    if latitude < 0:
        season_map = {
            "winter": "summer",
            "summer": "winter",
            "spring": "fall",
            "fall": "spring"
        }
        return season_map[northern_season]

    return northern_season


def get_month_context() -> Dict[str, Any]:
    """
    Get context about the current month for plant care.

    Returns:
        Dict with month name, week of month, and timing context
    """
    now = datetime.now()
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]

    week_of_month = (now.day - 1) // 7 + 1
    timing = "early" if week_of_month <= 1 else "mid" if week_of_month <= 2 else "late"

    return {
        "month": month_names[now.month - 1],
        "month_number": now.month,
        "week_of_month": week_of_month,
        "timing": timing,
        "day_of_year": now.timetuple().tm_yday,
    }


def get_seasonal_plant_tips(season: str, month: int) -> List[str]:
    """
    Get seasonal plant care tips.

    Args:
        season: Current season ('winter', 'spring', 'summer', 'fall')
        month: Current month number (1-12)

    Returns:
        List of relevant seasonal tips
    """
    tips = {
        "winter": [
            "Most houseplants enter a dormant period - reduce watering frequency",
            "Keep plants away from cold drafts and heating vents",
            "Indoor air is dry from heating - consider misting or using humidity trays",
            "Reduce or stop fertilizing until spring",
            "Dust accumulates on leaves - wipe them to help light absorption",
            "Watch for spider mites, which thrive in dry winter air",
            "Move plants closer to windows for maximum light during short days",
        ],
        "spring": [
            "Plants are waking up - gradually increase watering",
            "Now is the ideal time to repot plants that have outgrown their containers",
            "Start fertilizing again as plants enter active growth",
            "Watch for new pests as weather warms",
            "Consider propagating plants from cuttings",
            "Prune leggy growth from winter to encourage bushier plants",
            "Acclimate indoor plants slowly before moving them outside",
        ],
        "summer": [
            "Plants need more frequent watering in hot weather",
            "Provide shade for plants that can burn in intense afternoon sun",
            "Check soil moisture daily - containers dry out quickly",
            "Watch for heat stress: wilting, leaf curl, brown edges",
            "Morning watering is best - water evaporates too fast in afternoon heat",
            "Consider self-watering systems if traveling",
            "Move sensitive plants away from hot windows",
        ],
        "fall": [
            "Reduce watering as growth slows",
            "Bring outdoor plants inside before first frost",
            "Inspect plants for pests before bringing them indoors",
            "Gradually reduce fertilizing",
            "Clean up fallen leaves to prevent fungal issues",
            "This is a good time to take cuttings before dormancy",
            "Prepare plants for lower light conditions indoors",
        ],
    }

    base_tips = tips.get(season, [])

    # Add month-specific tips
    month_tips = {
        1: ["January is a good time to plan your spring garden"],
        2: ["Start seeds indoors for spring transplanting"],
        3: ["Watch for signs of new growth - spring is starting"],
        4: ["April showers: be mindful of outdoor plants getting too wet"],
        5: ["Safe to move most houseplants outdoors after last frost"],
        6: ["Peak growing season - plants may need extra nutrients"],
        7: ["Hottest month - water deeply and mulch outdoor plants"],
        8: ["Late summer pruning can shape plants before fall"],
        9: ["Prepare to bring tropical plants indoors"],
        10: ["Divide and transplant perennials before ground freezes"],
        11: ["Final chance to bring tender plants inside"],
        12: ["Minimal care needed - let plants rest"],
    }

    return base_tips + month_tips.get(month, [])


def get_weather_proactive_advice(
    weather: Optional[Dict[str, Any]] = None,
    forecast: Optional[List[Dict[str, Any]]] = None
) -> List[str]:
    """
    Generate proactive advice based on current weather conditions.

    Args:
        weather: Current weather data (temp, humidity, description, etc.)
        forecast: Weather forecast data

    Returns:
        List of weather-based care tips
    """
    tips = []

    if not weather:
        return tips

    temp = weather.get("temp")
    humidity = weather.get("humidity")
    description = weather.get("description", "").lower()

    # Temperature-based tips
    if temp is not None:
        if temp <= 32:  # Freezing
            tips.append("Freezing temperatures: keep tropical plants away from windows and doors")
            tips.append("Check that no plants are touching cold glass")
        elif temp <= 40:
            tips.append("Cold temperatures: tender plants should be kept warm indoors")
        elif temp >= 90:
            tips.append("High heat: water deeply and provide afternoon shade for sensitive plants")
            tips.append("Check soil moisture frequently - containers dry out fast in heat")
        elif temp >= 80:
            tips.append("Warm weather: most plants will appreciate extra water")

    # Humidity-based tips
    if humidity is not None:
        if humidity >= 85:
            tips.append("High humidity: reduce watering frequency and watch for fungal issues")
            tips.append("Ensure good air circulation around plants")
        elif humidity <= 30:
            tips.append("Low humidity: mist tropical plants or use humidity trays")
            tips.append("Group plants together to create a micro-climate")

    # Weather condition tips
    if "rain" in description:
        tips.append("Rainy weather: skip watering outdoor plants today")
        tips.append("Check that outdoor containers have drainage to prevent waterlogging")
    elif "snow" in description:
        tips.append("Snowy conditions: brush heavy snow off outdoor shrubs to prevent branch damage")
    elif "sunny" in description or "clear" in description:
        if temp and temp >= 75:
            tips.append("Sunny and warm: great growing conditions but watch for sunburn on sensitive leaves")
    elif "wind" in description:
        tips.append("Windy conditions: stake tall plants and check that containers won't tip over")
    elif "cloud" in description:
        tips.append("Overcast day: good time to transplant or prune without sun stress")

    # Forecast-based tips (look ahead)
    if forecast:
        for day in forecast[:3]:  # Look at next 3 days
            day_temp_min = day.get("temp_min")
            day_description = day.get("description", "").lower()

            if day_temp_min is not None and day_temp_min <= 35:
                tips.append(f"Frost warning in forecast: protect tender plants")
                break
            if "rain" in day_description:
                tips.append("Rain in the forecast: delay outdoor watering")
                break

    return tips[:5]  # Limit to 5 most relevant tips


def get_seasonal_context(
    latitude: float = 40.0,
    weather: Optional[Dict[str, Any]] = None,
    forecast: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Get comprehensive seasonal context for AI personalization.

    Args:
        latitude: User's latitude for hemisphere detection
        weather: Current weather data
        forecast: Weather forecast data

    Returns:
        Dict with season, month context, seasonal tips, and weather advice
    """
    season = get_current_season(latitude)
    month_context = get_month_context()
    seasonal_tips = get_seasonal_plant_tips(season, month_context["month_number"])
    weather_tips = get_weather_proactive_advice(weather, forecast)

    return {
        "season": season,
        "month": month_context["month"],
        "timing": f"{month_context['timing']} {month_context['month']}",
        "seasonal_tips": seasonal_tips[:3],  # Top 3 seasonal tips
        "weather_tips": weather_tips,
        "context_summary": f"It's {month_context['timing']} {month_context['month']} ({season})"
    }


def get_timely_focus(season: str, month: int) -> str:
    """
    Get a single focused recommendation for the current time.

    Args:
        season: Current season
        month: Current month number

    Returns:
        A single timely focus recommendation
    """
    focus_areas = {
        (1, "winter"): "Monitor humidity levels - heating systems dry out indoor air",
        (2, "winter"): "Plan your spring garden and order seeds",
        (3, "spring"): "Start inspecting plants for signs of new growth",
        (4, "spring"): "Begin repotting plants that need more room",
        (5, "spring"): "Acclimate indoor plants before moving outside",
        (6, "summer"): "Establish consistent watering routines for hot weather",
        (7, "summer"): "Focus on keeping plants hydrated in peak heat",
        (8, "summer"): "Take cuttings for propagation before growth slows",
        (9, "fall"): "Begin transitioning outdoor plants inside",
        (10, "fall"): "Inspect all plants for pests before bringing indoors",
        (11, "fall"): "Reduce watering and fertilizing as growth slows",
        (12, "winter"): "Let plants rest - minimal intervention needed",
    }

    return focus_areas.get(
        (month, season),
        f"Focus on maintaining consistent care routines for {season}"
    )
