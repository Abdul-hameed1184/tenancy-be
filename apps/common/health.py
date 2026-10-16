"""
Health endpoints for load balancers and orchestrators.

- /health/        liveness: the process is up and serving. Touches no dependency, so a
                  database or Redis blip never makes the orchestrator kill healthy web
                  processes.
- /health/ready/  readiness: can this instance do useful work? Requires PostgreSQL (the
                  system of record). Redis is *reported* but doesn't fail readiness: the
                  app degrades gracefully without it (cache misses, local throttles, no
                  live push). Pulling every pod out of the load balancer during a Redis
                  failover would turn a degradation into a full outage.
"""

import logging

from django.conf import settings
from django.core.cache import caches
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@never_cache
@require_GET
def liveness(request):
    return JsonResponse({"status": "ok"})


@never_cache
@require_GET
def readiness(request):
    checks = {"database": _check_database(), "redis": _check_redis()}
    ready = checks["database"] == "ok"
    return JsonResponse(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status=200 if ready else 503,
    )


def _check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("Readiness check: database unavailable")
        return "error"
    return "ok"


def _check_redis() -> str:
    if settings.REDIS.mode == "none":
        return "not_configured"
    try:
        # The throttle alias doesn't swallow errors, so this really reaches Redis.
        store = caches["throttle"]
        store.set("health:ping", "1", timeout=5)
        return "ok" if store.get("health:ping") == "1" else "degraded"
    except Exception:
        logger.warning("Readiness check: Redis unavailable", exc_info=True)
        return "degraded"
