# Plant Care AI Assistant, PlantCareAI

Flask application that provides plant-care guidance using a layered approach:
rule-based tips, local weather context, and optional OpenAI answers with graceful fallback to Google Gemini or to a basic rule-based engine if neither AI providers are available. The UI is accessible and CSP-compliant, with a loading indicator and geolocation-aware presets.

## Features

- Security: strict CSP, server-side validation, rate limiting, OpenAI moderation (input and output), PII redaction
- Usability: accepts “City, ST” and normalizes for weather; geocoding fallback; “thinking…” loader; responsive layout
- Accessibility: skip link, ARIA live regions, keyboard-friendly focus behavior; no inline scripts/styles
- Testability: app factory pattern; safe config access for calling AI without a Flask context; re-exports for legacy tests

## Quickstart

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# edit .env with real keys

python run.py
# visit http://127.0.0.1:5000/
```

## License

Licensed under the [MIT License](LICENSE).

© 2025 EDH Dev.  
The Plant Care AI Assistant, PlantCareAI, code is open source; the EDH Dev name and logo remain © EDH Dev.
