import logging

from django.core.cache import caches

logger = logging.getLogger(__name__)


class ResilientThrottleCache:
    """
    Throttle storage that survives a Redis outage.

    Rate limits are shared across processes through Redis ("throttle" alias, which does
    NOT ignore errors). If Redis is unreachable, the counters move to this process's
    memory ("local" alias). Limits then apply per process instead of globally, which is
    weaker but still bounded. Silently failing open, as a plain IGNORE_EXCEPTIONS cache
    would, would remove login brute-force protection exactly when an attacker might be
    causing the outage.

    Implements the two methods DRF's SimpleRateThrottle uses: get() and set().
    """

    def __init__(self, primary: str = "throttle", fallback: str = "local"):
        self.primary_alias = primary
        self.fallback_alias = fallback

    def get(self, key, default=None):
        try:
            return caches[self.primary_alias].get(key, default)
        except Exception:
            logger.warning("Throttle cache unavailable; using local fallback", exc_info=True)
            return caches[self.fallback_alias].get(key, default)

    def set(self, key, value, timeout=None):
        try:
            caches[self.primary_alias].set(key, value, timeout)
        except Exception:
            logger.warning("Throttle cache unavailable; using local fallback", exc_info=True)
            caches[self.fallback_alias].set(key, value, timeout)
