from .base import *  # noqa: F403
from .base import AUTH_REFRESH_COOKIE, REST_FRAMEWORK, env

DEBUG = env.bool("DEBUG", default=True)
SECRET_KEY = SECRET_KEY or "dev-only-insecure-secret-key-change-me"  # noqa: F405
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Local dev runs over plain http, where browsers drop Secure cookies.
AUTH_REFRESH_COOKIE = {
    **AUTH_REFRESH_COOKIE,
    "secure": env.bool("AUTH_COOKIE_SECURE", default=False),
}

# The browsable API is a convenience for humans exploring endpoints locally.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587

EMAIL_USE_TLS = True
EMAIL_USE_SSL = False

EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")