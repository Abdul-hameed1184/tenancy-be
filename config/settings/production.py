from email.utils import parseaddr

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email

from .base import *  # noqa: F403
from .base import env

DEBUG = False

if not SECRET_KEY or len(SECRET_KEY) < 50:  # noqa: F405
    raise ImproperlyConfigured("SECRET_KEY must be set to a long random value in production.")
if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set in production.")

# TLS is terminated at the proxy; trust its scheme header so request.is_secure() is correct.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# WhiteNoise serves collected static files (admin, Swagger UI) straight from the app
# container, right after SecurityMiddleware. Development uses runserver's static handler.
MIDDLEWARE = [*MIDDLEWARE]  # noqa: F405
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

# Compressed, content-hashed static files (cacheable forever).
STORAGES = {
    **STORAGES,  # noqa: F405
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LOGGING["handlers"]["console"]["formatter"] = env.str("LOG_FORMAT", default="json")  # noqa: F405

AUTH_REFRESH_COOKIE = {**AUTH_REFRESH_COOKIE, "secure": True}  # noqa: F405

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='[EMAIL_ADDRESS]')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='[PASSWORD]')
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
DEFAULT_FROM_EMAIL = env.str("EMAIL_USER", default="")



if not EMAIL_HOST or not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
    raise ImproperlyConfigured(
        "EMAIL_HOST, EMAIL_HOST_USER, and EMAIL_HOST_PASSWORD must be configured in production."
    )
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured("Use either EMAIL_USE_TLS or EMAIL_USE_SSL, not both.")

_from_address = parseaddr(DEFAULT_FROM_EMAIL)[1]
try:
    validate_email(_from_address)
except DjangoValidationError as exc:
    raise ImproperlyConfigured(
        "DEFAULT_FROM_EMAIL must contain a valid sender address on your verified mail domain."
    ) from exc
_from_domain = _from_address.rsplit("@", 1)[-1].lower()
if _from_domain.endswith((".local", ".test", ".example", ".invalid")):
    raise ImproperlyConfigured(
        "DEFAULT_FROM_EMAIL must use a real domain authenticated with SPF, DKIM, and DMARC."
    )
