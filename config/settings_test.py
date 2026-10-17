"""Settings for the automated test suite.

Run the suite with::

    .venv\\Scripts\\python.exe manage.py test tests --settings=config.settings_test

This mirrors the real settings but swaps the Supabase/PostgreSQL database for an
in-memory SQLite database and a fast password hasher, so tests run locally
without touching any remote service. Environment defaults are set before
``config.settings`` is imported so a local ``.env`` can never pull the suite
onto the production database.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost:5432/testdb")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from config.settings import *  # noqa: F401,F403,E402

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Keep URL loading (config.urls adds static() routes only when DEBUG) and error
# handling deterministic during tests.
DEBUG = False
