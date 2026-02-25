"""
Contains minimal heuristics to infer a user's climatic region from latitude/
longitude or city keywords, and returns a small curated set of plant presets
for the inferred region.
"""

def infer_region_from_latlon(lat: float, lon: float) -> str:
    """Approximate climate bands by absolute latitude."""
    abslat = abs(lat)
    if abslat < 23.5: return "tropical"
    if abslat < 35:   return "warm"
    if abslat < 45:   return "temperate"
    return "cool"

def infer_region_from_city(city: str | None) -> str:
    """Map common city names to regions using simple keyword checks."""
    if not city: return "temperate"
    c = city.lower()
    if any(k in c for k in ("miami","honolulu","hilo","key west")): return "tropical"
    if any(k in c for k in ("los angeles","san diego","phoenix","austin","las vegas","orlando","tampa")): return "warm"
    if any(k in c for k in ("seattle","portland","denver","kansas city","st louis","chicago","new york","boston")): return "temperate"
    if any(k in c for k in ("minneapolis","anchorage","calgary","winnipeg")): return "cool"
    return "temperate"

PRESET_LIBRARY = {
    "tropical": [
        {"plant":"Monstera deliciosa","why":"Native-like humidity & warmth","starter_care":"Bright-indirect light; water when top 2–3 cm dry."},
        {"plant":"Pothos (Epipremnum)","why":"Tolerant, thrives with warmth","starter_care":"Low-to-medium light; water when top 3–4 cm dry."},
        {"plant":"Areca palm","why":"Enjoys warm humid air","starter_care":"Bright-indirect; keep evenly moist; avoid cold drafts."},
    ],
    "warm": [
        {"plant":"Snake plant (Sansevieria)","why":"Handles heat & dry spells","starter_care":"Bright-to-medium light; let soil dry deeply."},
        {"plant":"Aloe vera","why":"Loves heat & sun","starter_care":"Full sun; water sparingly; very fast-draining mix."},
        {"plant":"ZZ plant (Zamioculcas)","why":"Forgiving in AC/heat","starter_care":"Low-to-medium light; water after soil fully dries."},
    ],
    "temperate": [
        {"plant":"Spider plant","why":"Adaptable household temps","starter_care":"Bright-indirect; keep slightly moist; good drainage."},
        {"plant":"Peace lily (Spathiphyllum)","why":"Blooming indoors, average temps","starter_care":"Medium light; water when leaves soften slightly."},
        {"plant":"Philodendron hederaceum","why":"Tolerant & fast growing","starter_care":"Medium-bright indirect; water when top inch dry."},
    ],
    "cool": [
        {"plant":"Chinese evergreen (Aglaonema)","why":"Tolerant of cooler rooms","starter_care":"Medium light; avoid overwatering; warm corners if possible."},
        {"plant":"Cast iron plant (Aspidistra)","why":"Handles low temps & neglect","starter_care":"Low-to-medium light; water sparingly."},
        {"plant":"Hoya carnosa","why":"Okay with cooler nights","starter_care":"Bright-indirect; let soil dry between waterings."},
    ],
}

def region_presets(region: str) -> list[dict]:
    """Return presets list for a region, defaulting to temperate."""
    return PRESET_LIBRARY.get(region, PRESET_LIBRARY["temperate"])
