"""
Serverless-compatible settings for platforms like Vercel, Netlify Functions, AWS Lambda.

DISABLED FEATURES (incompatible with serverless):
- Channels/WebSockets (requires persistent connections)
- Celery workers (requires long-running processes)
- Celery Beat (requires scheduled tasks)
- Redis (requires persistent state)

EMAIL BEHAVIOR:
- Emails sent synchronously (blocking) during request
- Acceptable for low traffic, not production-ready at scale
- For production, use a platform that supports background workers (Railway, Render, etc.)

LIMITATIONS:
- No real-time features (WebSocket chat, live notifications)
- No background tasks (email sending blocks the request)
- No scheduled tasks (rent reminders, cleanup jobs)
- Slower response times (email sending takes 1-3 seconds per request)
"""

from .base import *  # noqa: F403
from .base import INSTALLED_APPS, MIDDLEWARE, env

# --- Serverless Mode ------------------------------------------------------------------------

DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env.str("SECRET_KEY", default="")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

if not DEBUG and (not SECRET_KEY or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("SECRET_KEY must be set to a long random value.")  # noqa: F405

# --- Disable Channels/WebSockets ------------------------------------------------------------
# WebSockets require persistent connections - not possible in serverless

# Remove daphne (ASGI server for WebSockets)
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "daphne"]

# Remove channels and django_celery_beat
INSTALLED_APPS = [app for app in INSTALLED_APPS if app not in ["channels", "django_celery_beat"]]

# Use standard WSGI (no WebSocket support)
WSGI_APPLICATION = "config.wsgi.application"
# ASGI_APPLICATION is NOT set - no WebSocket support

# --- Disable Celery/Background Tasks --------------------------------------------------------
# Serverless functions are stateless and short-lived - no background workers

# Force synchronous task execution (tasks run during the request)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"  # In-memory broker (no Redis)
CELERY_RESULT_BACKEND = None

# Disable Celery Beat (scheduled tasks require persistent process)
CELERY_BEAT_SCHEDULE = {}

# --- Disable Redis --------------------------------------------------------------------------
# Serverless platforms don't support persistent Redis connections

# Use dummy cache (no caching)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}

# No channel layers (no WebSocket support anyway)
CHANNEL_LAYERS = {}

# --- Email Configuration --------------------------------------------------------------------
# Emails sent synchronously during the request (adds 1-3 seconds to response time)

EMAIL_BACKEND = env.str(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = env.str("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL")

# --- Security -------------------------------------------------------------------------------

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

AUTH_REFRESH_COOKIE = {**AUTH_REFRESH_COOKIE, "secure": not DEBUG}  # noqa: F405

# --- Static Files ---------------------------------------------------------------------------

# WhiteNoise serves static files in serverless environment
MIDDLEWARE = [*MIDDLEWARE]
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

STORAGES = {
    **STORAGES,  # noqa: F405
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Logging --------------------------------------------------------------------------------

LOGGING["handlers"]["console"]["formatter"] = env.str("LOG_FORMAT", default="json")  # noqa: F405

# --- Database -------------------------------------------------------------------------------
# Most serverless platforms provide PostgreSQL (Vercel Postgres, Neon, Supabase)

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default="postgresql://neondb_owner:npg_2Aank9tQDzeR@ep-curly-smoke-b8owbp9h-pooler.c-14.us-east-1.aws.neon.tech/neondb?channel_binding=require&sslmode=require"
    ),
}

# Shorter connection lifetime for serverless (functions are short-lived)
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0)  # No persistent connections
DATABASES["default"]["CONN_HEALTH_CHECKS"] = False
DATABASES["default"]["ATOMIC_REQUESTS"] = False

# --- Warnings -------------------------------------------------------------------------------

import warnings  # noqa: E402

# Warn about disabled features on startup
if not DEBUG:
    warnings.warn(
        "\n"
        "=" * 80 + "\n"
        "SERVERLESS MODE ACTIVE - FEATURES DISABLED:\n"
        "  - WebSockets/Real-time (Channels disabled)\n"
        "  - Background tasks (Celery workers disabled)\n"
        "  - Scheduled tasks (Celery Beat disabled)\n"
        "  - Redis caching (using DummyCache)\n"
        "  - Emails sent synchronously (adds 1-3s to requests)\n\n"
        "This configuration is suitable for:\n"
        "  - Development/Testing\n"
        "  - Low-traffic applications\n"
        "  - MVP/Proof of concept\n\n"
        "For production at scale, use Railway/Render/DigitalOcean with full workers.\n"
        "=" * 80,
        UserWarning
    )
