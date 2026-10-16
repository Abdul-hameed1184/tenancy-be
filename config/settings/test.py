from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = SECRET_KEY or "test-only-insecure-secret-key-padded-to-satisfy-hs256-length"  # noqa: F405
ALLOWED_HOSTS = ["testserver", "localhost"]

# Argon2 is intentionally slow; tests don't need that cost. Production hashing is asserted
# separately against the base PASSWORD_HASHERS setting.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Tests never depend on an external Redis: in-process cache, channel layer and inline tasks.
from .redis_topology import RedisTopology  # noqa: E402

CACHES = RedisTopology().caches()
CHANNEL_LAYERS = RedisTopology().channel_layers()
CELERY_BROKER_URL = "memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_RESULT_BACKEND = None

# daphne only upgrades `runserver` to ASGI; tests drive the ASGI app directly. (On Python
# 3.14/Windows its import also trips a deprecation in asyncio.)
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "daphne"]  # noqa: F405

# No persistent connections in tests: async consumers run DB work in worker threads, and a
# connection kept alive there would block dropping the test database at teardown.
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
