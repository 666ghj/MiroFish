"""Punt d'entrada WSGI per a gunicorn en producció."""
from app import create_app

application = create_app()
