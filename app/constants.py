"""
Shared constants used across the application.

This module contains constants that need to be consistent across
different parts of the application (forms, templates, validation, etc.).
"""

# Plant location options (used in plants form and AI assistant)
# Keep this in sync with care_context options
PLANT_LOCATIONS = [
    ('indoor_potted', 'Indoor (potted)'),
    ('outdoor_potted', 'Outdoor (potted)'),
    ('outdoor_bed', 'Outdoor (in-ground bed)'),
    ('greenhouse', 'Greenhouse'),
    ('office', 'Office'),
]

# Light level options for plants
LIGHT_LEVELS = [
    ('low', 'Low light (north-facing, no direct sun)'),
    ('medium', 'Medium light (east/west-facing, some direct sun)'),
    ('bright', 'Bright indirect light'),
    ('direct', 'Direct sunlight (south-facing)'),
]
