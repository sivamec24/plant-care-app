"""
Third-party extensions wiring.

Initializes shared Flask extension instances so other modules can import
configured objects without circular dependencies.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Limiter is initialized by create_app() with app config for storage/limits.
# Routes apply per-endpoint limits with @limiter.limit("X per minute") etc.

limiter = Limiter(key_func=get_remote_address)