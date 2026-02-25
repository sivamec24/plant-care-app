"""
Weather service helpers (OpenWeather).

Functions:
- get_weather_for_city(city): current weather for city OR US ZIP.
- get_forecast_for_city(city): 5–6 day daily forecast from the 3-hourly API.
- get_hourly_for_city(city): hourly chips for the rest of today; if none remain,
  return the first few hours of tomorrow (so the UI never feels empty).
- get_weather_alerts_for_city(current, forecast): simple derived alerts for heat/cold/wind.

Notes:
- Uses metric units from the API and converts to °F on the server. The UI toggles
  presentation only; no API re-requests needed.
- All functions are best-effort and return None/[] on failure to keep the UI responsive.
- Small emoji mapper improves glanceability while remaining neutral and accessible.
"""

from __future__ import annotations
import os
import time
from functools import lru_cache, wraps
from typing import Optional, Dict, List
import re
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from flask import current_app, has_app_context


# ============================================================================
# OPENWEATHER API RATE LIMITS & CACHING
# ============================================================================
# Free tier limit: 60 requests per minute (rpm)
# Caching strategy: 10-minute TTL per city keeps us well under the limit
# See: https://openweathermap.org/price

OPENWEATHER_FREE_TIER_RPM = 60      # Free tier: 60 requests per minute
OPENWEATHER_CACHE_TTL = 600         # 10 minutes - weather doesn't change fast
OPENWEATHER_CACHE_MAX_CITIES = 64   # Max cached cities per function

# Cache storage: {func_name: {cache_key: (timestamp, value)}}
_weather_cache: Dict[str, Dict[tuple, tuple]] = {}


def clear_weather_cache():
    """Clear all weather API caches. Useful for testing."""
    _weather_cache.clear()


def get_cache_stats() -> Dict[str, any]:
    """
    Get statistics about the weather cache.

    Returns dictionary with:
    - total_entries: Total cached items across all functions
    - by_function: Dict of function name to entry count
    - cached_cities: List of unique cities currently cached
    - cache_ttl: Current TTL setting in seconds
    - max_per_function: Max entries per function
    - oldest_entry_age: Age of oldest entry in seconds (or None)
    - newest_entry_age: Age of newest entry in seconds (or None)
    """
    current_time = time.time()
    stats = {
        "total_entries": 0,
        "by_function": {},
        "cached_cities": set(),
        "cache_ttl": OPENWEATHER_CACHE_TTL,
        "max_per_function": OPENWEATHER_CACHE_MAX_CITIES,
        "oldest_entry_age": None,
        "newest_entry_age": None,
        "free_tier_rpm": OPENWEATHER_FREE_TIER_RPM,
    }

    oldest_time = None
    newest_time = None

    for func_name, cache in _weather_cache.items():
        stats["by_function"][func_name] = len(cache)
        stats["total_entries"] += len(cache)

        for cache_key, (cached_time, _) in cache.items():
            # Track oldest/newest
            if oldest_time is None or cached_time < oldest_time:
                oldest_time = cached_time
            if newest_time is None or cached_time > newest_time:
                newest_time = cached_time

            # Extract city from cache key if possible
            args = cache_key[0]
            if args and isinstance(args[0], str):
                stats["cached_cities"].add(args[0])

    if oldest_time:
        stats["oldest_entry_age"] = round(current_time - oldest_time)
    if newest_time:
        stats["newest_entry_age"] = round(current_time - newest_time)

    # Convert set to sorted list for JSON serialization
    stats["cached_cities"] = sorted(stats["cached_cities"])

    return stats


def ttl_cache(seconds: int = OPENWEATHER_CACHE_TTL, maxsize: int = OPENWEATHER_CACHE_MAX_CITIES):
    """
    Simple TTL cache decorator for weather API calls.

    Caching is essential to stay under the OpenWeather free tier limit
    of {OPENWEATHER_FREE_TIER_RPM} requests per minute.

    Args:
        seconds: Cache TTL in seconds (default {OPENWEATHER_CACHE_TTL})
        maxsize: Maximum cache entries (default {OPENWEATHER_CACHE_MAX_CITIES})
    """
    def decorator(func):
        cache_name = func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from args and kwargs
            cache_key = (args, tuple(sorted(kwargs.items())))

            # Initialize cache for this function if needed
            if cache_name not in _weather_cache:
                _weather_cache[cache_name] = {}

            cache = _weather_cache[cache_name]
            current_time = time.time()

            # Check if we have a valid cached value
            if cache_key in cache:
                cached_time, cached_value = cache[cache_key]
                if current_time - cached_time < seconds:
                    return cached_value

            # Call the actual function
            result = func(*args, **kwargs)

            # Store in cache (evict oldest if at max size)
            if len(cache) >= maxsize:
                # Remove oldest entry
                oldest_key = min(cache.keys(), key=lambda k: cache[k][0])
                del cache[oldest_key]

            cache[cache_key] = (current_time, result)
            return result

        def cache_clear():
            if cache_name in _weather_cache:
                _weather_cache[cache_name].clear()

        wrapper.cache_clear = cache_clear
        return wrapper
    return decorator


_US_STATE_LIKE = re.compile(r"^([^,]+),\s?([A-Za-z]{2})$")
_US_ZIP = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")

# Hawaiian island names mapped to their main towns (for OpenWeather API compatibility)
_HAWAIIAN_ISLANDS = {
    "maui": "Kahului",
    "big island": "Hilo",
    "hawaii island": "Hilo",
    "kauai": "Lihue",
    "molokai": "Kaunakakai",
    "lanai": "Lanai City",
    "oahu": "Honolulu",
}

def _normalize_city_query(city: str) -> str:
    city = city.strip()
    m = _US_STATE_LIKE.match(city)
    if m:
        city_part = m.group(1).strip()
        state = m.group(2).upper()
        # Map Hawaiian island names to their main towns
        if state == "HI" and city_part.lower() in _HAWAIIAN_ISLANDS:
            return f"{_HAWAIIAN_ISLANDS[city_part.lower()]}, HI, US"
        return f"{city_part}, {state}, US"
    return city

def _get_api_key() -> str | None:
    key = os.getenv("OPENWEATHER_API_KEY")
    if not key and has_app_context():
        key = current_app.config.get("OPENWEATHER_API_KEY")
    return key or None

def _emoji_for(weather_id: int, main: str, descr: str) -> str:
    if 200 <= weather_id < 300: return "⛈️"
    if 300 <= weather_id < 400: return "🌦️"
    if 500 <= weather_id < 600: return "🌧️"
    if 600 <= weather_id < 700: return "❄️"
    if 700 <= weather_id < 800: return "🌫️"
    if weather_id == 800: return "☀️"
    if 801 <= weather_id <= 804: return "⛅" if weather_id in (801, 802) else "☁️"
    d = (descr or "").lower()
    if "rain" in d: return "🌧️"
    if "snow" in d: return "❄️"
    if "cloud" in d: return "☁️"
    if "clear" in d: return "☀️"
    return "🌤️"

@ttl_cache()  # Uses OPENWEATHER_CACHE_TTL and OPENWEATHER_CACHE_MAX_CITIES
def get_weather_for_city(city: str | None) -> Optional[Dict]:
    if not city:
        return None
    key = _get_api_key()
    if not key:
        return None

    base_url = "https://api.openweathermap.org/data/2.5/weather"
    session = requests.Session()

    def _call_q(q: str) -> requests.Response:
        return session.get(base_url, params={"q": q, "appid": key, "units": "metric"}, timeout=6)
    def _call_zip(zip5: str) -> requests.Response:
        return session.get(base_url, params={"zip": f"{zip5},US", "appid": key, "units": "metric"}, timeout=6)

    try:
        mzip = _US_ZIP.match(city)
        if mzip:
            r = _call_zip(mzip.group(1))
            if r.status_code == 404:
                r = _call_q(_normalize_city_query(city))
                if r.status_code == 404:
                    r = _call_q(city)
            r.raise_for_status()
        else:
            r = _call_q(_normalize_city_query(city))
            if r.status_code == 404:
                r = _call_q(city)
            r.raise_for_status()

        data = r.json()
        temp_c = data.get("main", {}).get("temp")
        wind_mps = data.get("wind", {}).get("speed")
        wid = (data.get("weather") or [{}])[0].get("id", 800)
        wmain = (data.get("weather") or [{}])[0].get("main", "")
        wdesc = (data.get("weather") or [{}])[0].get("description", "")

        # Extract coordinates for timezone derivation
        coord = data.get("coord", {})

        return {
            "city": data.get("name", city),
            "temp_c": temp_c,
            "temp_f": round((temp_c * 9 / 5) + 32, 1) if isinstance(temp_c, (int, float)) else None,
            "humidity": data.get("main", {}).get("humidity"),
            "conditions": wdesc,
            "wind_mps": wind_mps,
            "wind_mph": round(wind_mps * 2.23694, 1) if isinstance(wind_mps, (int, float)) else None,
            "emoji": _emoji_for(wid, wmain, wdesc),
            "lat": coord.get("lat"),
            "lon": coord.get("lon"),
        }
    except Exception:
        return None

@ttl_cache()  # Cache coords lookups
def _coords_for(city: str, key: str):
    """Auto-doc: see function name for purpose."""
    base = "https://api.openweathermap.org/data/2.5/weather"
    session = requests.Session()
    params = {"appid": key, "units": "metric"}
    mzip = _US_ZIP.match(city)
    if mzip:
        params["zip"] = f"{mzip.group(1)},US"
    else:
        params["q"] = _normalize_city_query(city)
    try:
        r = session.get(base, params=params, timeout=6)
        if r.status_code == 404 and not mzip:
            r = session.get(base, params={"q": city, "appid": key, "units": "metric"}, timeout=6)
        r.raise_for_status()
        data = r.json()
        coord = data.get("coord") or {}
        tz = data.get("timezone", 0)
        name = data.get("name", city)
        return coord.get("lat"), coord.get("lon"), tz, name
    except Exception:
        return None


def get_city_latitude(city: str | None) -> Optional[float]:
    """
    Get latitude for a city.

    Args:
        city: City name or US ZIP code

    Returns:
        Latitude as float, or None if city not found
    """
    if not city:
        return None
    key = _get_api_key()
    if not key:
        return None

    coords = _coords_for(city, key)
    if not coords:
        return None

    lat, _, _, _ = coords
    return lat


@ttl_cache()
def get_forecast_for_city(city: str | None) -> Optional[List[Dict]]:
    if not city:
        return None
    key = _get_api_key()
    if not key:
        return None

    coords = _coords_for(city, key)
    if not coords:
        return None
    lat, lon, tz_offset, _ = coords

    url = "https://api.openweathermap.org/data/2.5/forecast"
    try:
        r = requests.get(url, params={"lat": lat, "lon": lon, "appid": key, "units": "metric"}, timeout=8)
        r.raise_for_status()
        data = r.json()
        items = data.get("list") or []
        now_utc = datetime.now(tz=timezone.utc)
        today_local = (now_utc + timedelta(seconds=tz_offset)).strftime("%Y-%m-%d")

        by_date: dict[str, list[dict]] = defaultdict(list)
        for it in items:
            dt_utc = datetime.fromtimestamp(it["dt"], tz=timezone.utc)
            local_dt = dt_utc + timedelta(seconds=tz_offset)
            local_date = local_dt.strftime("%Y-%m-%d")
            by_date[local_date].append(it)

        daily = []
        for date_str, bucket in sorted(by_date.items()):
            temps = [x.get("main", {}).get("temp") for x in bucket if isinstance(x.get("main", {}).get("temp"), (int,float))]
            hums = [x.get("main", {}).get("humidity") for x in bucket if isinstance(x.get("main", {}).get("humidity"), (int,float))]
            winds = [x.get("wind", {}).get("speed") for x in bucket if isinstance(x.get("wind", {}).get("speed"), (int,float))]
            conds = [((x.get("weather") or [{}])[0].get("id", 800),
                      (x.get("weather") or [{}])[0].get("main", ""),
                      (x.get("weather") or [{}])[0].get("description","")) for x in bucket]
            if not temps:
                continue
            tmin_c = min(temps)
            tmax_c = max(temps)
            desc_counts = Counter([c[2] for c in conds if c[2]])
            top_desc = (desc_counts.most_common(1)[0][0]) if desc_counts else "clear sky"
            wid, wmain, wdesc = conds[0] if conds else (800, "Clear", top_desc)
            emoji = _emoji_for(wid, wmain, top_desc)

            dt_obj = datetime.strptime(date_str, "%Y-%m-%d")
            day = dt_obj.strftime("%a")

            daily.append({
                "date": date_str,
                "day": day,
                "is_today": date_str == today_local,
                "temp_min_c": round(tmin_c, 1),
                "temp_max_c": round(tmax_c, 1),
                "temp_min_f": round((tmin_c * 9/5) + 32, 1),
                "temp_max_f": round((tmax_c * 9/5) + 32, 1),
                "humidity": round(sum(hums)/len(hums)) if hums else None,
                "wind_mps": round(sum(winds)/len(winds), 1) if winds else None,
                "wind_mph": round((sum(winds)/len(winds)) * 2.23694, 1) if winds else None,
                "conditions": top_desc,
                "emoji": emoji,
            })

        return daily[:6]
    except Exception:
        return None

def _fmt_hour_label(dt_local: datetime) -> str:
    # Cross-platform 12h format without leading zero
    label = dt_local.strftime("%I%p")  # e.g., "01PM"
    return label.lstrip("0") if label[0] == "0" else label

@ttl_cache()
def get_hourly_for_city(city: str | None) -> Optional[List[Dict]]:
    """Return all upcoming hourly entries (3-hour steps) from the forecast API.

    Each entry includes a ``date_label`` (e.g. "Mon") so the UI can show
    date-change dividers in the scrollable row.
    """
    if not city:
        return None
    key = _get_api_key()
    if not key:
        return None

    coords = _coords_for(city, key)
    if not coords:
        return None
    lat, lon, tz_offset, _ = coords

    url = "https://api.openweathermap.org/data/2.5/forecast"
    try:
        r = requests.get(url, params={"lat": lat, "lon": lon, "appid": key, "units": "metric"}, timeout=8)
        r.raise_for_status()
        data = r.json()
        items = data.get("list") or []

        now_local = datetime.now(timezone.utc) + timedelta(seconds=tz_offset)
        today_str = now_local.strftime("%Y-%m-%d")
        tomorrow_str = (now_local + timedelta(days=1)).strftime("%Y-%m-%d")

        upcoming = []

        for it in items:
            dt_local = datetime.fromtimestamp(it["dt"], tz=timezone.utc) + timedelta(seconds=tz_offset)
            if dt_local <= now_local:
                continue

            date_str = dt_local.strftime("%Y-%m-%d")
            if date_str > tomorrow_str:
                break

            temp_c = it.get("main", {}).get("temp")
            if not isinstance(temp_c, (int, float)):
                continue

            wid = (it.get("weather") or [{}])[0].get("id", 800)
            wmain = (it.get("weather") or [{}])[0].get("main", "")
            wdesc = (it.get("weather") or [{}])[0].get("description", "")

            upcoming.append({
                "time": _fmt_hour_label(dt_local),
                "temp_c": temp_c,
                "temp_f": round((temp_c * 9/5) + 32, 1),
                "emoji": _emoji_for(wid, wmain, wdesc),
                "is_tomorrow": date_str == tomorrow_str,
                "date_label": dt_local.strftime("%a"),
            })

        return upcoming
    except Exception:
        return None

def get_weather_alerts_for_city(current: Optional[Dict], forecast: Optional[List[Dict]]) -> List[Dict]:
    alerts: List[Dict] = []
    try:
        if current and isinstance(current.get("temp_f"), (int, float)):
            if current["temp_f"] >= 95:
                alerts.append({"title": "Heat Advisory", "desc": "High temperatures. Water may evaporate quickly."})
            if current["temp_f"] <= 35:
                alerts.append({"title": "Freeze Risk", "desc": "Protect sensitive plants from cold exposure."})
        if current and isinstance(current.get("wind_mph"), (int, float)) and current["wind_mph"] >= 20:
            alerts.append({"title": "Windy Conditions", "desc": "Strong winds can increase transpiration and stress."})

        if forecast:
            for d in forecast[:2]:
                if isinstance(d.get("temp_max_f"), (int,float)) and d["temp_max_f"] >= 95:
                    alerts.append({"title": "Upcoming Heat", "desc": f"Highs near {round(d['temp_max_f'])}°F expected."})
                if isinstance(d.get("temp_min_f"), (int,float)) and d["temp_min_f"] <= 35:
                    alerts.append({"title": "Cold Overnight", "desc": f"Lows near {round(d['temp_min_f'])}°F expected."})
                if isinstance(d.get("wind_mph"), (int,float)) and d["wind_mph"] >= 20:
                    alerts.append({"title": "Windy Forecast", "desc": "Elevated winds expected. Consider wind protection."})
    except Exception:
        return []

    seen = set()
    unique = []
    for a in alerts:
        key = (a["title"], a["desc"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(a)
    return unique


# ============================================================================
# WEATHER-AWARE REMINDERS: Enhanced Intelligence Functions
# ============================================================================

def get_precipitation_last_48h(city: str | None) -> Optional[float]:
    """
    Get total precipitation in inches over past 48 hours.

    Note: OpenWeather free tier doesn't include historical data.
    This function returns None to indicate unavailable data.
    Reminder adjustment logic should gracefully handle None values.

    Args:
        city: City name or US ZIP code

    Returns:
        Total precipitation in inches, or None if unavailable
    """
    # OpenWeather free tier limitation: no historical precipitation data
    # Future enhancement: integrate paid tier or alternative weather service
    return None


@ttl_cache()
def get_precipitation_forecast_24h(city: str | None) -> Optional[float]:
    """
    Get expected precipitation in next 24 hours from forecast.

    Args:
        city: City name or US ZIP code

    Returns:
        Expected precipitation in inches, or None on error

    Note: Uses 3-hourly forecast data. Precipitation is estimated
    from weather conditions (rain/snow).
    """
    if not city:
        return None
    key = _get_api_key()
    if not key:
        return None

    coords = _coords_for(city, key)
    if not coords:
        return None
    lat, lon, tz_offset, _ = coords

    url = "https://api.openweathermap.org/data/2.5/forecast"
    try:
        r = requests.get(url, params={"lat": lat, "lon": lon, "appid": key, "units": "metric"}, timeout=8)
        r.raise_for_status()
        data = r.json()
        items = data.get("list") or []

        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc + timedelta(hours=24)

        total_precip_mm = 0.0
        for it in items:
            dt_utc = datetime.fromtimestamp(it["dt"], tz=timezone.utc)
            if now_utc <= dt_utc <= cutoff:
                # Extract precipitation from rain and snow fields
                rain_mm = it.get("rain", {}).get("3h", 0)  # 3-hour rainfall
                snow_mm = it.get("snow", {}).get("3h", 0)  # 3-hour snowfall
                total_precip_mm += rain_mm + snow_mm

        # Convert mm to inches (1 inch = 25.4 mm)
        total_precip_inches = total_precip_mm / 25.4
        return round(total_precip_inches, 2)

    except Exception:
        return None


@ttl_cache()
def get_temperature_extremes_forecast(city: str | None, hours: int = 48) -> Optional[Dict]:
    """
    Get min/max temperatures in forecast period.

    Args:
        city: City name or US ZIP code
        hours: Forecast period in hours (default: 48)

    Returns:
        {
            "temp_min_f": float,
            "temp_max_f": float,
            "temp_min_c": float,
            "temp_max_c": float,
            "freeze_risk": bool  # True if min temp <= 32°F
        }
        or None on error
    """
    if not city:
        return None
    key = _get_api_key()
    if not key:
        return None

    coords = _coords_for(city, key)
    if not coords:
        return None
    lat, lon, tz_offset, _ = coords

    url = "https://api.openweathermap.org/data/2.5/forecast"
    try:
        r = requests.get(url, params={"lat": lat, "lon": lon, "appid": key, "units": "metric"}, timeout=8)
        r.raise_for_status()
        data = r.json()
        items = data.get("list") or []

        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc + timedelta(hours=hours)

        temps_c = []
        for it in items:
            dt_utc = datetime.fromtimestamp(it["dt"], tz=timezone.utc)
            if now_utc <= dt_utc <= cutoff:
                temp = it.get("main", {}).get("temp")
                if isinstance(temp, (int, float)):
                    temps_c.append(temp)

        if not temps_c:
            return None

        min_c = min(temps_c)
        max_c = max(temps_c)
        min_f = (min_c * 9 / 5) + 32
        max_f = (max_c * 9 / 5) + 32

        return {
            "temp_min_f": round(min_f, 1),
            "temp_max_f": round(max_f, 1),
            "temp_min_c": round(min_c, 1),
            "temp_max_c": round(max_c, 1),
            "freeze_risk": min_f <= 32
        }

    except Exception:
        return None


def get_seasonal_pattern(
    city: str | None, latitude: float | None = None
) -> Optional[Dict]:
    """
    Determine current season based on actual weather patterns + calendar fallback.

    Hybrid approach:
    1. Analyzes last 7 days of weather patterns (if available)
    2. Falls back to calendar-based seasons (hemisphere-aware)
    3. Detects dormancy periods and frost risk

    Args:
        city: City name or US ZIP code
        latitude: Optional latitude for hemisphere detection.
                  If not provided, will be auto-detected from city.
                  Positive = Northern Hemisphere, Negative = Southern Hemisphere.

    Returns:
        {
            "season": "winter|spring|summer|fall",
            "is_dormancy_period": bool,  # True for winter/late fall
            "avg_temp_7d": float,  # Average temperature (estimated)
            "frost_risk": bool,  # True if freezing temps in forecast
            "method": "weather|calendar"  # Data source used
        }
        or None on error
    """
    if not city:
        return None

    # Get current weather and forecast for pattern analysis
    current = get_weather_for_city(city)
    extremes = get_temperature_extremes_forecast(city, hours=48)

    # Auto-detect latitude if not provided (for hemisphere detection)
    if latitude is None:
        latitude = get_city_latitude(city)

    # Detect hemisphere (negative latitude = Southern Hemisphere)
    is_southern = latitude is not None and latitude < 0

    # Calendar-based fallback
    now = datetime.now()
    month = now.month

    # Meteorological seasons (flip for Southern Hemisphere)
    if is_southern:
        # Southern Hemisphere: seasons are flipped
        if month in [12, 1, 2]:
            calendar_season = "summer"
        elif month in [3, 4, 5]:
            calendar_season = "fall"
        elif month in [6, 7, 8]:
            calendar_season = "winter"
        else:  # 9, 10, 11
            calendar_season = "spring"
    else:
        # Northern Hemisphere (or unknown)
        if month in [12, 1, 2]:
            calendar_season = "winter"
        elif month in [3, 4, 5]:
            calendar_season = "spring"
        elif month in [6, 7, 8]:
            calendar_season = "summer"
        else:  # 9, 10, 11
            calendar_season = "fall"

    if not current or not extremes:
        # Calendar fallback only
        return {
            "season": calendar_season,
            "is_dormancy_period": calendar_season in ["winter", "fall"] and month in [11, 12, 1, 2],
            "avg_temp_7d": None,
            "frost_risk": calendar_season == "winter",
            "method": "calendar"
        }

    # Weather-based season detection
    current_temp = current.get("temp_f", 60)
    min_forecast = extremes.get("temp_min_f", 32)
    freeze_risk = extremes.get("freeze_risk", False)

    # Estimate average temperature (current + forecast average)
    avg_temp = (current_temp + min_forecast + extremes.get("temp_max_f", 80)) / 3

    # Determine season from temperature patterns
    if avg_temp >= 75:
        weather_season = "summer"
    elif avg_temp >= 55:
        weather_season = "spring" if month in [3, 4, 5, 6] else "fall"
    elif avg_temp >= 40:
        weather_season = "spring" if month in [3, 4] else "fall"
    else:
        weather_season = "winter"

    # Dormancy period: winter or cold fall/early spring
    is_dormancy = weather_season == "winter" or (avg_temp < 45 and month in [11, 12, 1, 2, 3])

    return {
        "season": weather_season,
        "is_dormancy_period": is_dormancy,
        "avg_temp_7d": round(avg_temp, 1),
        "frost_risk": freeze_risk,
        "method": "weather"
    }


def infer_hardiness_zone(city: str | None, state: str | None = None) -> Optional[str]:
    """
    Infer USDA hardiness zone from city coordinates.

    Uses a simplified lookup table based on latitude and average winter temperatures.
    For production, consider integrating with a comprehensive hardiness zone API.

    Args:
        city: City name or US ZIP code
        state: Optional state abbreviation for disambiguation

    Returns:
        USDA zone string (e.g., "7a", "7b", "8a"), or None if unable to determine

    Note: This is a simplified implementation. For accurate hardiness zones,
    consider using USDA's official Plant Hardiness Zone Map API or dataset.
    """
    if not city:
        return None

    key = _get_api_key()
    if not key:
        return None

    coords = _coords_for(city, key)
    if not coords:
        return None

    lat, lon, _, _ = coords

    # Simplified hardiness zone lookup based on latitude (U.S. focused)
    # Source: USDA Plant Hardiness Zone Map (simplified approximation)
    # Zones range from 1 (coldest) to 13 (warmest)

    # Latitude-based approximation (rough estimates for U.S.)
    if lat >= 48:  # Northern border
        return "3b" if lat >= 49 else "4a"
    elif lat >= 45:
        return "5a"
    elif lat >= 42:
        return "6a"
    elif lat >= 39:
        return "7a"
    elif lat >= 36:
        return "7b" if lat >= 37.5 else "8a"
    elif lat >= 33:
        return "8b"
    elif lat >= 30:
        return "9a" if lat >= 31.5 else "9b"
    elif lat >= 27:
        return "10a"
    elif lat >= 24:
        return "10b"
    else:  # Southern Florida, Hawaii
        return "11a"

    # Future enhancement: Use actual USDA zone data with more precise lookup