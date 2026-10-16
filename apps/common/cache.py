"""
Versioned read-through caching.

Key layout (Django adds the "pleet:<version>:" prefix):

    cache:<namespace>:version                  integer, never expires
    cache:<namespace>:<name>:v<N>:<hash>       cached payload, expires after its TTL

Invalidating a namespace is a single INCR of its version. All existing entries become
unreachable at once and age out through their TTL. That avoids KEYS/SCAN (O(N), and
blocking on a production Redis) and avoids racing a concurrent writer that's
repopulating the old key.

Failure mode: the default cache uses IGNORE_EXCEPTIONS, so with Redis unreachable every
lookup is a miss and `producer()` serves from PostgreSQL. Slower, never wrong.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Mapping

from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)

_NO_EXPIRY = None


def _version_key(namespace: str) -> str:
    return f"cache:{namespace}:version"


def namespace_version(namespace: str) -> int:
    version = cache.get(_version_key(namespace))
    if version is None:
        cache.add(_version_key(namespace), 1, timeout=_NO_EXPIRY)
        version = cache.get(_version_key(namespace)) or 1
    return int(version)


def bump(namespace: str) -> None:
    try:
        cache.incr(_version_key(namespace))
    except ValueError:  # key missing (first write, eviction or Redis restart)
        cache.set(_version_key(namespace), 2, timeout=_NO_EXPIRY)


def invalidate_on_commit(*namespaces: str) -> None:
    """Bump after the transaction commits, so readers never cache pre-commit state."""

    def _bump():
        for namespace in namespaces:
            bump(namespace)

    transaction.on_commit(_bump, robust=True)


def make_key(namespace: str, name: str, params: Mapping | None = None) -> str:
    canonical = json.dumps(
        sorted((k, sorted(params.getlist(k)) if hasattr(params, "getlist") else v)
               for k, v in (params or {}).items()),
        default=str,
    )  # fmt: skip
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:24]
    return f"cache:{namespace}:{name}:v{namespace_version(namespace)}:{digest}"


def cached(namespace: str, name: str, params: Mapping | None, ttl: int, producer: Callable):
    key = make_key(namespace, name, params)
    data = cache.get(key)
    if data is not None:
        return data
    data = producer()  # exceptions (e.g. a 400 from bad filters) propagate and aren't cached
    cache.set(key, data, timeout=ttl)
    return data
