"""
Settings shared by every environment.

Environment-specific modules (development / production / test) import * from here and
override only what differs. All secrets and deployment-specific values come from the
environment (or a local, git-ignored .env file) — never from source control.
"""

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

from .redis_topology import RedisTopology

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# --- Core -----------------------------------------------------------------------------------

# Required in production (enforced there); dev/test provide a throwaway fallback.
SECRET_KEY = env.str("SECRET_KEY", default="")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["tenancy-be.vercel.app"],)

DJANGO_APPS = [
    # daphne first: it makes `runserver` an ASGI server (HTTP + WebSocket) in development.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "channels",
    "django_celery_beat",
]
LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.agents",
    "apps.properties",
    "apps.tenancies",
    "apps.payments",
    "apps.maintenance",
    "apps.inspections",
    "apps.messaging",
    "apps.notifications",
    "apps.reports",
    "apps.dashboards",
    "apps.audit",
    "apps.uploads",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "apps.common.middleware.RequestIdMiddleware",  # first: every later log line gets the id
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # must run before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database -------------------------------------------------------------------------------

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL", default="postgresql://neondb_owner:npg_2Aank9tQDzeR@ep-curly-smoke-b8owbp9h-pooler.c-14.us-east-1.aws.neon.tech/neondb?channel_binding=require&sslmode=require"
    ),
}
# Persistent connections avoid a TCP+auth handshake per request; health checks drop
# connections that died while idle (e.g. after a Postgres failover) instead of erroring.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
# Deliberately NOT using ATOMIC_REQUESTS: services own their transaction boundaries, so
# side effects (events, emails) can be tied to transaction.on_commit precisely.
DATABASES["default"]["ATOMIC_REQUESTS"] = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth -----------------------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

# Argon2id first (memory-hard, OWASP recommended); PBKDF2 kept so existing hashes still verify.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

JWT_ACCESS_TOKEN_LIFETIME = timedelta(minutes=env.int("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", 60))
JWT_REFRESH_TOKEN_LIFETIME = timedelta(days=env.int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", 14))

# simplejwt only signs/validates tokens. Session state (rotation, revocation, reuse
# detection) lives in accounts.AuthSession.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": JWT_ACCESS_TOKEN_LIFETIME,
    "REFRESH_TOKEN_LIFETIME": JWT_REFRESH_TOKEN_LIFETIME,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "ISSUER": "pleet",
    "LEEWAY": 10,  # seconds of clock skew tolerated between servers
    "UPDATE_LAST_LOGIN": False,
}
# A dedicated key lets JWTs be rotated without invalidating password-reset links (which
# are signed with SECRET_KEY). When unset, simplejwt falls back to SECRET_KEY.
if JWT_SIGNING_KEY := env.str("JWT_SIGNING_KEY", default=""):
    SIMPLE_JWT["SIGNING_KEY"] = JWT_SIGNING_KEY

# The refresh token never reaches JavaScript: HttpOnly cookie, scoped to the auth routes.
AUTH_REFRESH_COOKIE = {
    "key": "pleet_refresh",
    "path": "/api/v1/auth/",
    "httponly": True,
    "secure": env.bool("AUTH_COOKIE_SECURE", default=True),
    "samesite": "Lax",
}

# Verification links stay valid for three days (signed + timestamped, no table needed).
EMAIL_VERIFICATION_TIMEOUT = env.int("EMAIL_VERIFICATION_TIMEOUT", default=3 * 24 * 60 * 60)

# Reset links are valid for one hour (Django's default is three days).
PASSWORD_RESET_TIMEOUT = env.int("PASSWORD_RESET_TIMEOUT", default=60 * 60)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="PLEET <no-reply@pleet.local>")

# --- Internationalisation -------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
# Store and emit UTC ("...Z") as the contract's examples do. Business rules that depend on
# the local calendar ("today", "this month") use PLEET_BUSINESS_TIME_ZONE explicitly.
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
PLEET_BUSINESS_TIME_ZONE = "Africa/Lagos"
# Landlord dashboards estimate asset value as annual rent roll x this multiplier.
PORTFOLIO_VALUE_MULTIPLIER = env.int("PORTFOLIO_VALUE_MULTIPLIER", default=6)

# --- Static / media -------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Swappable later for S3/Cloudinary via django-storages without touching model code.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")
MEDIA_URL = "media/"

# Direct-to-Cloudinary image uploads (apps.uploads). The API secret signs upload parameters
# server-side and never reaches the browser. Leave unset to disable uploads (503).
CLOUDINARY_CLOUD_NAME = env.str("CLOUDINARY_CLOUD_NAME", default="")
CLOUDINARY_API_KEY = env.str("CLOUDINARY_API_KEY", default="")
CLOUDINARY_API_SECRET = env.str("CLOUDINARY_API_SECRET", default="")
CLOUDINARY_ROOT_FOLDER = env.str("CLOUDINARY_ROOT_FOLDER", default="pleet")
# Must match the account's setting (Cloudinary console > Settings > Security). Default sha1.
CLOUDINARY_SIGNATURE_ALGORITHM = env.str("CLOUDINARY_SIGNATURE_ALGORITHM", default="sha1")

# Reject oversized JSON bodies before they are parsed.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --- CORS -----------------------------------------------------------------------------------

FRONTEND_URL = env.str("FRONTEND_URL", default="http://localhost:5173")
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[FRONTEND_URL, "https://tenancy-fe.vercel.app"],
)
# Needed later for the HttpOnly refresh-token cookie; Authorization/Content-Type are in the
# default allowed headers.
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

# --- Django REST Framework ------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.SessionJWTAuthentication"],
    # Secure by default: every endpoint requires auth unless it explicitly opts out.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    # The contract returns full arrays. Pagination can be enabled per view later (opt-in via
    # query param) without changing the default response shape.
    "DEFAULT_PAGINATION_CLASS": None,
    "EXCEPTION_HANDLER": "apps.common.exceptions.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    # Only trust X-Forwarded-For when this many proxies sit in front of the app.
    "NUM_PROXIES": env.int("NUM_PROXIES", default=None),
    "DEFAULT_THROTTLE_RATES": {
        "login": "5/min",
        "register": "10/hour",
        "password_reset": "3/min",
        "token_refresh": "30/min",
        "email_verification": "3/min",
        "upload_signature": "120/hour",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "PLEET API",
    "DESCRIPTION": "Property and rental management platform API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+",
    "PREPROCESSING_HOOKS": ["apps.common.schema.drop_trailing_slash_duplicates"],
    "ENUM_NAME_OVERRIDES": {
        "RoleEnum": "apps.accounts.serializers.ROLE_CHOICES",
        "SelfRegisterRoleEnum": "apps.accounts.serializers.SELF_REGISTER_ROLE_CHOICES",
        # Every domain has its own `status`; name each enum explicitly.
        "PropertyStatusEnum": "apps.properties.models.PROPERTY_STATUS_CHOICES",
        "PaymentStatusEnum": "apps.payments.models.PAYMENT_STATUS_CHOICES",
        "MaintenanceStatusEnum": "apps.maintenance.models.MAINTENANCE_STATUS_CHOICES",
        "InspectionStatusEnum": "apps.inspections.models.INSPECTION_STATUS_CHOICES",
        "VerificationStatusEnum": "apps.agents.models.VERIFICATION_STATUS_CHOICES",
        "NotificationTypeEnum": "apps.notifications.models.NOTIFICATION_TYPE_CHOICES",
        "ReportStatusEnum": "apps.reports.models.REPORT_STATUS_CHOICES",
        "ReportTypeEnum": "apps.reports.models.REPORT_TYPE_CHOICES",
    },
}

# --- Logging --------------------------------------------------------------------------------

LOG_LEVEL = env.str("LOG_LEVEL", default="INFO")
LOG_FORMAT = env.str("LOG_FORMAT", default="text")  # "json" in production
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "apps.common.logging.RequestIdFilter"},
        # Redaction is attached to the handler, so it covers every logger, ours or not.
        "redact": {"()": "apps.common.logging.RedactingFilter"},
    },
    "formatters": {
        "text": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s"},
        "json": {"()": "apps.common.logging.JSONFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
            "filters": ["request_id", "redact"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        # The access line is ours (apps.common.middleware); drop Django's duplicate.
        "django.server": {"level": "WARNING"},
        "pleet.access": {"level": env.str("ACCESS_LOG_LEVEL", default="INFO")},
    },
}

# --- Redis: cache, channel layer, Celery broker -------------------------------------------
# One topology description feeds all three (see redis_topology.py). In production this is
# REDIS_SENTINELS: a primary, two replicas and three sentinels, so no Redis node is a
# single point of failure.

REDIS = RedisTopology.from_env(env)
CACHES = REDIS.caches()
CHANNEL_LAYERS = REDIS.channel_layers()
DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True  # a swallowed Redis error still gets logged
if REDIS.mode == "sentinel":
    # django-redis asks the sentinels for the current primary (and re-asks after failover).
    DJANGO_REDIS_CONNECTION_FACTORY = "django_redis.pool.SentinelConnectionFactory"

# --- Realtime -----------------------------------------------------------------------------

WS_TICKET_TTL_SECONDS = 30

# --- Celery -------------------------------------------------------------------------------

_broker_url, _transport_options = REDIS.celery_broker()
CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default=_broker_url)
CELERY_BROKER_TRANSPORT_OPTIONS = _transport_options
CELERY_RESULT_BACKEND = env.str("CELERY_RESULT_BACKEND", default="") or None
CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = _transport_options
# With no broker configured, tasks run inline. That keeps local development and tests to
# a single process while exercising exactly the same task code.
CELERY_TASK_ALWAYS_EAGER = env.bool(
    "CELERY_TASK_ALWAYS_EAGER", default=CELERY_BROKER_URL == "memory://"
)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True  # a task killed mid-run is redelivered, not lost
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = PLEET_BUSINESS_TIME_ZONE  # crontab hours below are Lagos time
CELERY_TASK_TIME_LIMIT = 120
CELERY_TASK_SOFT_TIME_LIMIT = 100
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    "relay-pending-events": {
        "task": "apps.common.tasks.relay_pending_events",
        "schedule": 30.0,
    },
    "rent-due-reminders": {
        "task": "apps.payments.tasks.send_rent_due_reminders",
        "schedule": crontab(hour=7, minute=0),
    },
    "overdue-rent-sweep": {
        "task": "apps.payments.tasks.flag_overdue_rent",
        "schedule": crontab(hour=0, minute=15),
    },
    "cleanup-auth-sessions": {
        "task": "apps.accounts.tasks.cleanup_auth_sessions",
        "schedule": crontab(hour=3, minute=0),
    },
    "purge-dispatched-events": {
        "task": "apps.common.tasks.purge_dispatched_events",
        "schedule": crontab(hour=4, minute=0, day_of_week="sun"),
    },
}
CELERY_WORKER_HIJACK_ROOT_LOGGER = False  # workers use LOGGING above (JSON + redaction)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='[EMAIL_ADDRESS]')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='[PASSWORD]')