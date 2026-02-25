"""
Production WSGI entry point for Render or Gunicorn.

Gunicorn (or Render's runtime) will import this file and look for
a top-level variable named `app`.

Usage (Render / CLI):
    gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT wsgi:app
"""

from app import create_app

# Gunicorn looks for a top-level 'app' variable here.
app = create_app()
