"""
Advice engine (AI-first with safe fallback).

Attempts to get guidance from OpenAI when available; otherwise falls back
to a compact rule set. Adds a short weather hint if current temperature is known.
OpenAI usage is isolated and failures never break the request flow.
"""

from __future__ import annotations
import os
from typing import Tuple, Optional, Dict, Any

from flask import current_app, has_app_context
from .weather import get_weather_for_city
from . import user_context

# Most recent AI error (shown in UI/Debug to help diagnose model/key issues)

AI_LAST_ERROR: Optional[str] = None

# Track which AI provider was actually used for the last successful response
AI_LAST_PROVIDER: Optional[str] = None

# Cache for LiteLLM Router to avoid recreating on every request
_ROUTER_CACHE: Optional[object] = None

# Locations treated as indoor for weather filtering purposes
_INDOOR_LOCATIONS = frozenset({"indoor_potted", "office", "greenhouse"})


def _clear_router_cache():
    """Clear the router cache. Used for testing and when API keys change."""
    global _ROUTER_CACHE
    _ROUTER_CACHE = None


def _get_litellm_router():
    """
    Returns a LiteLLM Router configured with OpenAI (primary) and Gemini (fallback),
    or (None, error) if neither API key is available.

    Reads API keys from environment first; if a Flask app context is active,
    also checks current_app.config.

    PERFORMANCE: Router is cached to avoid recreation on every request.
    """
    global _ROUTER_CACHE

    # Return cached router if available
    if _ROUTER_CACHE is not None:
        return _ROUTER_CACHE, None

    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if not openai_key and has_app_context():
        openai_key = current_app.config.get("OPENAI_API_KEY")
    if not gemini_key and has_app_context():
        gemini_key = current_app.config.get("GEMINI_API_KEY")

    if not openai_key and not gemini_key:
        return None, "Neither OPENAI_API_KEY nor GEMINI_API_KEY configured"

    try:
        from litellm import Router

        model_list = []
        fallbacks = {}

        # Add OpenAI as primary if key exists
        if openai_key:
            model_list.append({
                "model_name": "primary-gpt",
                "litellm_params": {
                    "model": "gpt-4o-mini",
                    "api_key": openai_key,
                    "temperature": 0.5,  # Balanced for natural variation
                    "max_tokens": 1500,  # Increased from 350 to match Gemini
                }
            })

        # Add Gemini as fallback if key exists
        if gemini_key:
            model_list.append({
                "model_name": "fallback-gemini",
                "litellm_params": {
                    "model": "gemini/gemini-flash-latest",
                    "api_key": gemini_key,
                    "temperature": 0.5,  # Balanced for natural variation
                    "max_tokens": 1500,  # Increased from 350 to avoid truncation
                }
            })

        # Configure fallback chain: OpenAI -> Gemini
        if openai_key and gemini_key:
            fallbacks = [{"primary-gpt": ["fallback-gemini"]}]

        router = Router(
            model_list=model_list,
            fallbacks=fallbacks if fallbacks else None,
            num_retries=2,
            timeout=30,
        )

        # Cache the router for future requests
        _ROUTER_CACHE = router
        return router, None
    except Exception as e:
        return None, f"LiteLLM Router initialization error: {e}"

def _fmt_temp(weather: Optional[dict]) -> str:
    """Return a compact temperature string using both units when available."""
    if not weather:
        return "n/a"
    t_c = weather.get("temp_c")
    t_f = weather.get("temp_f")
    try:
        if isinstance(t_c, (int, float)) and isinstance(t_f, (int, float)):
            return f"~{t_c:.0f}°C / {t_f:.0f}°F"
        if isinstance(t_c, (int, float)):
            return f"~{t_c:.0f}°C"
        if isinstance(t_f, (int, float)):
            return f"~{t_f:.0f}°F"
    except Exception:
        pass
    return "n/a"

def _weather_tip(weather: Optional[dict], plant: Optional[str], care_context: Optional[str] = None) -> Optional[str]:
    """
    Tiny, safe hint based on temperature (thresholds in °C), but display both °C/°F when possible.
    Only shows tips for outdoor plants (outdoor_potted, outdoor_bed).

    Args:
        weather: Weather dict with temp_c and optional care_context
        plant: Plant name for personalization
        care_context: Location context (outdoor_potted, outdoor_bed, indoor_potted, etc.)
                     Can also be passed in weather dict as weather["care_context"]
    """
    if not weather or weather.get("temp_c") is None:
        return None

    # Get care_context from parameter or weather dict, default to outdoor_potted for backward compatibility
    context = care_context or weather.get("care_context", "outdoor_potted")

    # Only show weather tips for outdoor plants (not indoor/office/greenhouse)
    if context in _INDOOR_LOCATIONS:
        return None

    t_c = weather["temp_c"]
    temp_str = _fmt_temp(weather)
    name = plant or "the plant"
    try:
        if t_c >= 32:
            return f"It's hot ({temp_str}). Check {name} more often; water may evaporate quickly."
        if t_c <= 5:
            return f"It's cold ({temp_str}). Keep {name} away from drafts and reduce watering."
        return f"Current temp {temp_str}. Maintain your usual schedule; verify soil moisture first."
    except Exception:
        return None


def _basic_plant_tip(question: str, plant: Optional[str], care_context: str) -> str:
    """
    Minimal rules for a predictable fallback response. Slight phrasing changes
    make answers feel relevant without needing a large ruleset.
    """
    q = (question or "").lower()
    p = (plant or "").strip() or "the plant"

    loc = {
        "indoor_potted": f"{p} indoors",
        "outdoor_potted": f"{p} outdoors in a pot",
        "outdoor_bed": f"{p} in a garden bed",
    }.get(care_context, p)

    if "water" in q:
        return f"For {loc}, water when the top 2–3 cm of soil is dry. Soak thoroughly and ensure drainage."
    if "light" in q or "sun" in q:
        return f"{loc.capitalize()} generally prefers bright, indirect light unless it’s sun-tolerant."
    if "fertil" in q or "feed" in q:
        return f"Feed {loc} at 1/4–1/2 strength every 4–6 weeks during active growth; reduce in winter."
    if "repot" in q or "pot" in q:
        return f"Repot {loc} only when root-bound; choose a pot 2–5 cm wider with a free-draining mix."
    return f"For {loc}, aim for bright-indirect light, water when the top inch is dry, and ensure good drainage."


def detect_question_type(question: str, selected_plant_id: Optional[str]) -> str:
    """
    Detect question type to determine appropriate context level.

    Returns "plant" (Tier 2) or "diagnosis" (Tier 3 premium) based on question content.
    All questions default to rich plant-aware context (Tier 2).
    Diagnosis questions with health concerns trigger premium diagnostic features (Tier 3).

    Args:
        question: User's question text
        selected_plant_id: Whether user selected a specific plant

    Returns:
        "plant" - Plant-specific rich context (Tier 2 default)
        "diagnosis" - Full diagnostic context with health trends (Tier 3 premium)

    Examples:
        >>> detect_question_type("Why are my leaves yellow?", "plant-123")
        'diagnosis'
        >>> detect_question_type("How often should I water?", "plant-123")
        'plant'
    """
    q_lower = question.lower()

    # Diagnosis indicators (trigger premium Tier 3 features)
    diagnosis_keywords = [
        "yellow", "brown", "droopy", "drooping", "wilting", "wilt",
        "dying", "dead", "sick", "unhealthy", "problem", "wrong",
        "help", "issue", "concern", "worry", "pest", "bug", "disease",
        "spots", "curling", "crispy", "mushy", "rot"
    ]

    if any(kw in q_lower for kw in diagnosis_keywords):
        return "diagnosis"

    # All other questions use rich plant-aware context (Tier 2)
    return "plant"


def is_watering_question(question: str) -> bool:
    """
    Detect if question is asking about watering recommendations.

    Args:
        question: User's question text

    Returns:
        True if question is about watering

    Examples:
        >>> is_watering_question("Should I water my plant today?")
        True
        >>> is_watering_question("What type of soil should I use?")
        False
    """
    q_lower = question.lower()

    # Watering question patterns
    watering_keywords = [
        "should i water", "do i need to water", "time to water",
        "water today", "water my", "watering", "need water",
        "how much water", "when to water", "water schedule",
        "water now", "ready for water", "thirsty",
        "needs water", "need watering"
    ]

    return any(keyword in q_lower for keyword in watering_keywords)


def _get_response_guidance(question: str) -> str:
    """
    Determine response length and format guidance based on question type.

    Provides adaptive instructions to keep responses natural and appropriately sized
    for the UI Answer card (~800 characters max for desktop fit).

    Args:
        question: User's question text

    Returns:
        Format and length guidance string for the AI
    """
    q_lower = question.lower()

    # Diagnostic questions first - most specific signal, avoids mis-classification
    # when diagnostic keywords co-occur with yes/no phrases
    if any(kw in q_lower for kw in [
        "why is", "what's wrong", "yellow", "brown", "drooping",
        "wilting", "dying", "spots", "curling"
    ]):
        return (
            "Identify the most likely cause first, then suggest 2-3 solutions. "
            "Respond in 4-6 sentences (under 700 characters)."
        )

    # Simple yes/no or "should I" questions - direct answers
    if any(kw in q_lower for kw in ["should i", "can i", "is it", "when should"]):
        return (
            "Answer directly first, then briefly explain why. "
            "Respond in 2-3 sentences (under 400 characters)."
        )

    # How-to questions - clear steps
    if any(kw in q_lower for kw in ["how do i", "how to", "how often", "how much"]):
        return (
            "Provide clear, practical steps. Use a numbered list only if sequence matters. "
            "Respond in 3-5 sentences (under 600 characters)."
        )

    # General care questions - conversational tips
    return (
        "Be helpful and conversational. Use 2-4 key points if listing tips. "
        "Respond in 4-7 sentences (under 800 characters)."
    )


def build_system_prompt(
    user_context_data: Optional[Dict[str, Any]] = None,
    context_level: str = "plant"
) -> str:
    """
    Build AI system prompt with enhanced context and weather awareness.

    Args:
        user_context_data: Enhanced context from get_enhanced_user_context(),
                          get_enhanced_plant_context(), or
                          get_enhanced_context_for_empty_user()
        context_level: "plant" (Tier 2 default) or "diagnosis" (Tier 3 premium)

    Returns:
        System prompt string with rich context and weather insights
    """
    base = (
        "You are a friendly, knowledgeable plant care advisor—like a neighbor who's great with plants. "
        "Give practical, actionable advice in a warm, conversational tone. "
        "Reference the user's specific situation using the provided context. "
        "Do not invent details about the user's plants or history that are not in the context. "
        "If you're uncertain, say so honestly. "
        "Only answer questions about plant care, gardening, and related topics. "
        "Respond in plain text with short paragraphs. No markdown formatting."
    )

    if not user_context_data:
        return base

    # Check for user preferences context and adapt tone
    user_prefs = user_context_data.get("user_preferences", {})
    if user_prefs:
        experience = user_prefs.get("experience_level")
        if experience == "beginner":
            base = (
                "You are a patient, encouraging plant mentor helping someone new to plant care. "
                "Explain concepts simply without jargon. Give clear, step-by-step guidance. "
                "Reassure them that mistakes are part of learning. "
                "Keep advice practical and achievable. "
                "Reference the user's specific situation using the provided context. "
                "Do not invent details not in the context. "
                "Only answer questions about plant care, gardening, and related topics. "
                "Respond in plain text with short paragraphs. No markdown formatting."
            )
        elif experience == "expert":
            base = (
                "You are a fellow plant enthusiast having a knowledgeable conversation. "
                "Use technical terminology when useful. Discuss nuances and trade-offs. "
                "Skip basics and get to the specifics. Share insights they might not know. "
                "Reference the user's specific situation using the provided context. "
                "Do not invent details not in the context. "
                "Only answer questions about plant care, gardening, and related topics. "
                "Respond in plain text with short paragraphs. No markdown formatting."
            )

    # Build enhanced context summary for prompt
    context_lines = []

    # USER PREFERENCES (for personalization even without plant data)
    if user_prefs:
        if user_prefs.get("goal_description"):
            context_lines.append(f"User goal: {user_prefs['goal_description']}")
        if user_prefs.get("time_description"):
            context_lines.append(f"Time commitment: {user_prefs['time_description']}")
        if user_prefs.get("environment_description"):
            context_lines.append(f"Environment: {user_prefs['environment_description']}")

    # SEASONAL CONTEXT (proactive tips based on date/season)
    seasonal = user_context_data.get("seasonal")
    if seasonal:
        context_lines.append(f"Current timing: {seasonal.get('context_summary', '')}")
        if seasonal.get("timely_focus"):
            context_lines.append(f"Seasonal focus: {seasonal['timely_focus']}")
        # Add top seasonal tips
        seasonal_tips = seasonal.get("seasonal_tips", [])
        if seasonal_tips:
            context_lines.append("Seasonal tips to consider:")
            for tip in seasonal_tips[:2]:  # Limit to 2 tips
                context_lines.append(f"  - {tip}")

    # WEATHER TIPS (proactive weather-based advice)
    weather_data = user_context_data.get("weather")
    if weather_data and weather_data.get("tips"):
        weather_tips = weather_data["tips"]
        if weather_tips:
            context_lines.append("Weather-aware tips:")
            for tip in weather_tips[:2]:  # Limit to 2 tips
                context_lines.append(f"  - {tip}")

    # PERSONALIZED GUIDANCE (for users without plant data)
    guidance = user_context_data.get("personalized_guidance", [])
    if guidance:
        context_lines.append("Personalized guidance for this user:")
        for g in guidance[:2]:  # Limit to 2
            context_lines.append(f"  - {g}")

    # WEATHER CONTEXT (Phase 2 - Weather-aware AI)
    weather_context = user_context_data.get("weather_context")
    if weather_context:
        context_lines.append(f"Current weather: {weather_context}")

    # FORECAST CONTEXT (Phase 2B - Forecast awareness for rain/temperature predictions)
    forecast = user_context_data.get("forecast")
    if forecast:
        if forecast.get("precipitation_24h_inches") is not None:
            precip = forecast["precipitation_24h_inches"]
            if precip > 0.1:
                context_lines.append(f"Forecast: {precip:.2f} inches rain expected in next 24h")
            else:
                context_lines.append(f"Forecast: No significant rain expected (next 24h)")

        temp_extremes = forecast.get("temperature_extremes")
        if temp_extremes:
            min_f = temp_extremes.get("temp_min_f")
            max_f = temp_extremes.get("temp_max_f")
            freeze_risk = temp_extremes.get("freeze_risk", False)

            if freeze_risk:
                context_lines.append(f"Temperature forecast: {min_f}°F to {max_f}°F (FREEZE RISK)")
            elif min_f and max_f:
                context_lines.append(f"Temperature forecast (48h): {min_f}°F to {max_f}°F")

    # WATERING RECOMMENDATION (intelligent stress-based analysis)
    watering_rec = user_context_data.get("watering_recommendation")
    if watering_rec:
        rec_text = watering_rec.get("recommendation", "")
        reason = watering_rec.get("reason", "")
        if rec_text:
            context_lines.append(f"Watering analysis: {rec_text}")
            if reason:
                context_lines.append(f"  Reason: {reason}")

    # USER'S PLANTS with notes and patterns
    plants = user_context_data.get("plants", [])
    if plants:
        for p in plants[:5]:  # Limit to 5 plants
            plant_info = p.get("name", "Unknown")
            if p.get("species"):
                plant_info += f" ({p['species']})"

            # Add notes if available
            if p.get("notes"):
                plant_info += f" - {p['notes']}"

            # Add watering pattern if available
            if p.get("watering_pattern"):
                plant_info += f" [watered {p['watering_pattern']}]"

            context_lines.append(f"Plant: {plant_info}")

    # SPECIFIC PLANT CONTEXT (from get_enhanced_plant_context)
    plant_details = user_context_data.get("plant")
    if plant_details:
        plant_name = plant_details.get("name", "Plant")
        context_lines.append(f"Selected plant: {plant_name}")

        # Add full plant notes
        if plant_details.get("notes_full"):
            notes = plant_details["notes_full"]
            context_lines.append(f"Plant notes: {notes}")

        # Add care history summary
        care_history = plant_details.get("care_history_summary", {})
        if care_history.get("avg_watering_interval_days"):
            interval = care_history["avg_watering_interval_days"]
            consistency = care_history.get("watering_consistency", "")
            context_lines.append(f"Watering pattern: every ~{interval} days ({consistency})")

        if care_history.get("care_level"):
            care_level = care_history["care_level"]
            context_lines.append(f"Care level: {care_level}")

        # INITIAL ASSESSMENT (baseline from when plant was added)
        # This provides context especially for new plants without journal history
        initial = plant_details.get("initial_assessment")
        if initial:
            context_lines.append("Initial assessment (baseline when added):")
            if initial.get("health_state"):
                context_lines.append(f"  • Starting health: {initial['health_state']}")
            if initial.get("ownership_duration"):
                duration_map = {
                    "just_got": "just acquired",
                    "few_weeks": "owned a few weeks",
                    "few_months": "owned a few months",
                    "year_plus": "owned over a year"
                }
                duration = duration_map.get(initial["ownership_duration"], initial["ownership_duration"])
                context_lines.append(f"  • When added: {duration}")
            if initial.get("watering_schedule"):
                context_lines.append(f"  • Original watering: {initial['watering_schedule']}")
            if initial.get("concerns"):
                context_lines.append(f"  • Initial concerns: {initial['concerns'][:100]}")

    # RECENT OBSERVATIONS with health keywords
    # Note: These are more current indicators than initial assessment
    recent_obs = user_context_data.get("recent_observations", [])
    if recent_obs:
        context_lines.append("Recent observations:")
        for obs in recent_obs[:3]:  # Max 3
            days_ago = obs.get("days_ago", 0)
            note = obs.get("note_preview", "")
            if obs.get("has_concern"):
                context_lines.append(f"  ⚠ {days_ago}d ago: {note}")
            else:
                context_lines.append(f"  • {days_ago}d ago: {note}")

    # RECENT CARE ACTIVITIES (Phase 2B - detailed actions with dates for "When did I last..." questions)
    activities = user_context_data.get("activities_detailed", [])
    if activities:
        context_lines.append("Recent care activities:")
        for activity in activities[:10]:  # Limit to 10 most recent
            action_type = activity.get("action_type", "unknown")
            days_ago = activity.get("days_ago", 0)
            amount_ml = activity.get("amount_ml")
            notes = activity.get("notes")

            # Format: "3d ago: watered (500ml) - soil was very dry"
            activity_str = f"  {days_ago}d ago: {action_type}"
            if amount_ml:
                activity_str += f" ({amount_ml}ml)"
            if notes:
                activity_str += f" - {notes[:50]}"  # Truncate notes to 50 chars

            context_lines.append(activity_str)

    # HEALTH PATTERNS (for diagnosis context level)
    if context_level == "diagnosis":
        health_trends = user_context_data.get("health_trends")
        if health_trends:
            concerns = health_trends.get("recent_concerns", [])
            if concerns:
                context_lines.append(f"Health concerns: {', '.join(concerns)}")

            if health_trends.get("improving"):
                context_lines.append("Trend: Improving (fewer issues recently)")
            elif health_trends.get("deteriorating"):
                context_lines.append("Trend: Deteriorating (more issues recently)")

        # Comparative insights (premium)
        comparative = user_context_data.get("comparative_insights")
        if comparative:
            vs_avg = comparative.get("watering_vs_user_avg")
            if vs_avg == "more_frequent_than_others":
                context_lines.append("This plant is watered more frequently than user's other plants")
            elif vs_avg == "less_frequent_than_others":
                context_lines.append("This plant is watered less frequently than user's other plants")

    # REMINDERS (handle both dict from user context and list from plant context)
    reminders = user_context_data.get("reminders", {})
    if reminders:
        # Check if reminders is a dict (from get_enhanced_user_context)
        # or a list (from get_enhanced_plant_context)
        if isinstance(reminders, dict):
            due_today = reminders.get("due_today", [])
            if due_today:
                tasks = [r["title"] for r in due_today[:3]]
                context_lines.append(f"Care due today: {', '.join(tasks)}")

            overdue = reminders.get("overdue", [])
            if overdue:
                context_lines.append(f"Overdue tasks: {len(overdue)}")
        elif isinstance(reminders, list):
            # Plant-specific context returns list of reminders
            if reminders:
                tasks = [r.get("title", r.get("reminder_type", "task")) for r in reminders[:3]]
                context_lines.append(f"Active reminders: {', '.join(tasks)}")

    # Build final context section
    if context_lines:
        context_section = "\n\nUser Context (use this to personalize your advice):\n" + "\n".join(f"- {line}" for line in context_lines)
        return base + context_section

    return base


def _ai_advice(
    question: str,
    plant: Optional[str],
    weather: Optional[dict],
    care_context: str,
    user_context_data: Optional[Dict[str, Any]] = None,
    context_level: str = "plant"
) -> Tuple[Optional[str], Optional[str]]:
    """
    Calls AI providers using LiteLLM Router (OpenAI primary, Gemini fallback).
    Returns (response_text, provider_name) or (None, None) if all providers fail.
    The caller will use rule-based output if this returns (None, None).

    Args:
        question: User's question
        plant: Plant name/species
        weather: Weather dict
        care_context: Location context
        user_context_data: Enhanced context data
        context_level: "plant" (Tier 2) or "diagnosis" (Tier 3)

    Returns:
        Tuple of (response_text, provider_name) or (None, None)
    """
    global AI_LAST_ERROR, AI_LAST_PROVIDER
    AI_LAST_ERROR = None
    AI_LAST_PROVIDER = None

    router, err = _get_litellm_router()
    if not router:
        AI_LAST_ERROR = err or "AI Router initialization failed"
        return None, None

    # Compact weather summary included in the prompt when available.
    w_summary = None
    if weather:
        parts = []
        city = weather.get("city")
        if city:
            parts.append(f"city: {city}")

        temp_c = weather.get("temp_c")
        if temp_c is not None:
            parts.append(f"temp_c: {temp_c}")

        temp_f = weather.get("temp_f")
        if temp_f is not None:
            parts.append(f"temp_f: {temp_f}")

        hum = weather.get("humidity")
        if hum is not None:
            parts.append(f"humidity: {hum}%")

        cond = weather.get("conditions")
        if cond:
            parts.append(f"conditions: {cond}")

        # Only include wind data for outdoor plants (not relevant for indoor plants)
        is_outdoor = care_context in ("outdoor_potted", "outdoor_bed")
        if is_outdoor:
            wind_mps = weather.get("wind_mps")
            if wind_mps is not None:
                parts.append(f"wind_mps: {wind_mps}")

            wind_mph = weather.get("wind_mph")
            if wind_mph is not None:
                parts.append(f"wind_mph: {wind_mph}")

        w_summary = ", ".join(parts) if parts else None

    context_map = {
        "indoor_potted": "potted house plant (indoors)",
        "outdoor_potted": "potted plant kept outdoors",
        "outdoor_bed": "plant grown in an outdoor garden bed",
        "greenhouse": "plant grown in a greenhouse",
        "office": "plant kept in an office or workspace",
    }
    context_str = context_map.get(care_context, "potted house plant (indoors)")

    # Add indoor-specific weather guidance to context
    if care_context in _INDOOR_LOCATIONS:
        context_str += (
            " - Note: Indoor plants are shielded from direct outdoor weather effects. "
            "Outdoor conditions only matter for: (1) light levels through windows on cloudy days, "
            "(2) dry indoor air during heating season, (3) cold drafts if placed near windows/doors in winter."
        )

    # Build system message with enhanced user context and context level
    sys_msg = build_system_prompt(user_context_data, context_level=context_level)

    # Append compact weather summary if not already covered by user_context_data
    has_weather_in_context = (
        user_context_data
        and (user_context_data.get("weather_context") or user_context_data.get("weather"))
    )
    if w_summary and not has_weather_in_context:
        sys_msg += f"\n\nCurrent weather: {w_summary}"

    # Get adaptive response guidance based on question type
    response_guidance = _get_response_guidance(question)

    user_msg = (
        f"Plant: {(plant or '').strip() or 'unspecified'}\n"
        f"Care context: {context_str}\n"
        f"Question: {question.strip()}\n\n"
        f"{response_guidance}"
    )

    try:
        # Use LiteLLM Router with automatic fallback
        # Start with primary model (OpenAI if configured)
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key and has_app_context():
            openai_key = current_app.config.get("OPENAI_API_KEY")

        model_to_use = "primary-gpt" if openai_key else "fallback-gemini"

        resp = router.completion(
            model=model_to_use,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.7,
            max_tokens=300,
        )

        txt = (resp.choices[0].message.content or "").strip()

        if txt:
            # Determine which provider was actually used
            model_used = getattr(resp, "model", None) or model_to_use
            if "gemini" in model_used.lower():
                AI_LAST_PROVIDER = "gemini"
                return txt, "gemini"
            else:
                AI_LAST_PROVIDER = "openai"
                return txt, "openai"

        AI_LAST_ERROR = "Empty response from AI providers"
        return None, None
    except Exception as e:
        # Never raise; capture a short reason for /debug and the template.
        AI_LAST_ERROR = str(e)[:300]
        return None, None


def ai_advice(
    question: str,
    plant: str | None,
    weather: dict | None,
    care_context: str | None = "indoor_potted",
) -> str | None:
    """
    Back-compat shim for any code/tests that import ai_advice directly.
    Returns just the text response, discarding the provider information.
    """
    text, _provider = _ai_advice(question, plant, weather, care_context or "indoor_potted", None)
    return text


def generate_advice(
    question: str,
    plant: Optional[str],
    city: Optional[str],
    care_context: str,
    user_id: Optional[str] = None,
    selected_plant_id: Optional[str] = None,
) -> Tuple[str, Optional[dict], str]:
    """
    Orchestrates advice generation with enhanced context and weather awareness.

    Enhanced with:
      - Rich plant-aware context (Tier 2 default for all users)
      - Premium diagnostic features (Tier 3 for premium users)
      - Weather-aware insights integrated into context
      - Pattern recognition from care history
      - Health trend analysis

    Steps:
      1) Fetch weather data (best-effort)
      2) Detect question type (plant vs diagnosis)
      3) Fetch enhanced user context with weather awareness
      4) Try AI providers (OpenAI primary, Gemini fallback) with rich context
      5) Fallback to rules if AI unavailable

    Args:
        question: User's plant care question
        plant: Plant name or species
        city: City for weather data
        care_context: indoor_potted, outdoor_potted, or outdoor_bed
        user_id: Optional user ID for context fetching
        selected_plant_id: Optional specific plant ID for detailed context

    Returns:
        Tuple of (answer, weather, source: "openai"|"gemini"|"rule")
    """
    # Fetch weather first (needed for weather-aware context)
    weather = get_weather_for_city(city) if city else None

    # Fetch forecast data for rain/temperature predictions (Phase 2B)
    from .weather import (
        get_precipitation_forecast_24h,
        get_temperature_extremes_forecast
    )
    forecast_precip = get_precipitation_forecast_24h(city) if city else None
    forecast_temps = get_temperature_extremes_forecast(city, hours=48) if city else None

    # Detect question type to determine context level
    context_level = detect_question_type(question, selected_plant_id)

    # Determine if user has premium tier (TODO: integrate with subscription system)
    # For now, diagnosis questions trigger premium features for all users
    is_premium = (context_level == "diagnosis")

    # Fetch enhanced user context if authenticated
    user_context_data = None
    if user_id:
        try:
            if selected_plant_id:
                # Get enhanced plant-specific context with weather
                user_context_data = user_context.get_enhanced_plant_context(
                    user_id,
                    selected_plant_id,
                    weather=weather,
                    is_premium=is_premium
                )
            else:
                # Get enhanced general user context with weather
                user_context_data = user_context.get_enhanced_user_context(
                    user_id,
                    weather=weather
                )

                # Check if user has plants - if not, use enriched "cold start" context
                # This provides value to new users even without plant data
                stats = user_context_data.get("stats", {})
                if stats.get("total_plants", 0) == 0:
                    # Get latitude from weather if available (for hemisphere detection)
                    latitude = weather.get("lat", 40.0) if weather else 40.0

                    # Build enriched context for users without plants
                    user_context_data = user_context.get_enhanced_context_for_empty_user(
                        user_id,
                        weather=weather,
                        forecast=None,  # TODO: Pass forecast data
                        latitude=latitude
                    )
        except Exception as e:
            # If context fetch fails, continue without it (graceful degradation)
            # Log error for debugging
            from app.utils.errors import log_info
            log_info(f"Context fetch failed: {str(e)}")
            user_context_data = None

    # Detect watering questions and generate intelligent recommendations
    if is_watering_question(question) and selected_plant_id and weather:
        try:
            from . import watering_intelligence
            from .journal import get_last_watered_date

            # Get last watered date for stress calculation
            last_watered = get_last_watered_date(selected_plant_id, user_id) if user_id else None

            # Calculate hours since watered
            hours_since_watered = None
            if last_watered:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                if last_watered.tzinfo is None:
                    # Make timezone-aware if naive
                    from datetime import timezone
                    last_watered = last_watered.replace(tzinfo=timezone.utc)
                hours_since_watered = (now - last_watered).total_seconds() / 3600

            # Determine plant type from care_context
            plant_type = "houseplant"
            if care_context == "outdoor_bed":
                # Could be shrubs or wildflowers - default to shrub
                plant_type = "outdoor_shrub"
            elif care_context == "outdoor_potted":
                plant_type = "outdoor_shrub"

            # Generate watering recommendation
            watering_rec = watering_intelligence.generate_watering_recommendation(
                plant_name=plant or "Your plant",
                hours_since_watered=hours_since_watered,
                weather=weather,
                plant_type=plant_type,
                plant_age_weeks=None,  # TODO: Track plant age for wildflowers
                hours_since_rain=None,  # TODO: Track rain data
                recent_rain=False,  # TODO: Integrate rain tracking
                rain_expected=False  # TODO: Check forecast for rain
            )

            # Add watering recommendation to context
            if user_context_data is None:
                user_context_data = {}
            user_context_data["watering_recommendation"] = watering_rec

        except Exception as e:
            # If watering intelligence fails, continue without it
            from app.utils.errors import log_info
            log_info(f"Watering intelligence failed: {str(e)}")
            pass

    # Add forecast data to context (Phase 2B)
    if forecast_precip is not None or forecast_temps is not None:
        if user_context_data is None:
            user_context_data = {}
        user_context_data["forecast"] = {
            "precipitation_24h_inches": forecast_precip,
            "temperature_extremes": forecast_temps
        }

    # Call AI with enhanced context (context_level passed to build_system_prompt)
    ai_text, provider = _ai_advice(
        question,
        plant,
        weather,
        care_context,
        user_context_data,
        context_level=context_level
    )

    if ai_text and provider:
        answer = ai_text
        source = provider  # "openai" or "gemini"
    else:
        answer = _basic_plant_tip(question, plant, care_context)
        source = "rule"

    # Weather tip is now integrated into context, but keep as fallback for non-authenticated
    if not user_id:
        hint = _weather_tip(weather, plant, care_context)
        if hint:
            city_name = weather.get("city") if weather else (city or "")
            suffix = f"\n\nWeather tip{(' for ' + city_name) if city_name else ''}: {hint}"
            answer = f"{answer}{suffix}"

    return answer, weather, source