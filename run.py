"""
Local development entry point.

Creates the Flask app via create_app() and runs the dev server. Keeps startup
simple and avoids embedding app logic here.
"""

import os
from app import create_app

# Allow overriding config via environment variable for dev/test flexibility
os.environ.setdefault("APP_CONFIG", "app.config.DevConfig")

app = create_app()

if __name__ == "__main__":
    # Use host='0.0.0.0' so it’s reachable on LAN (e.g., for testing on mobile)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=os.getenv("FLASK_DEBUG", "1") == "1")
