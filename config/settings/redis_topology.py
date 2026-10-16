"""
Builds cache, channel-layer and Celery settings from one Redis description, so all three
always agree on where Redis is and how to fail over.

Modes, in order of preference:

1. REDIS_SENTINELS=host1:26379,host2:26379,host3:26379 (+ REDIS_MASTER_NAME)
   High availability. Clients ask the sentinels who the current primary is, and re-ask
   after a failover. No single Redis node is a single point of failure.
2. REDIS_URL=redis://host:6379
   A single node, for simple local development.
3. Neither: no Redis. LocMem cache, in-memory channel layer, Celery runs tasks inline.
   This only works within one process; it is for tests and quick local runs.

Logical databases: 0 = Celery broker/results, 1 = cache/throttles/WS tickets,
2 = channel layer. Key prefixes: "pleet:" (cache), "pleet:channels" (channel layer).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedisTopology:
    sentinels: list[tuple[str, int]] = field(default_factory=list)
    master_name: str = "pleet-core"
    url: str = ""
    password: str = ""
    socket_timeout: float = 0.5  # fail fast so a dead node degrades quickly

    @property
    def mode(self) -> str:
        if self.sentinels:
            return "sentinel"
        if self.url:
            return "single"
        return "none"

    @classmethod
    def from_env(cls, env) -> RedisTopology:
        sentinels = []
        for entry in env.list("REDIS_SENTINELS", default=[]):
            host, _, port = entry.strip().rpartition(":")
            sentinels.append((host, int(port)))
        return cls(
            sentinels=sentinels,
            master_name=env.str("REDIS_MASTER_NAME", default="pleet-core"),
            url=env.str("REDIS_URL", default=""),
            password=env.str("REDIS_PASSWORD", default=""),
        )

    # --- Django cache ---------------------------------------------------------------------

    def caches(self) -> dict:
        local = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "pleet"}
        if self.mode == "none":
            return {
                "default": {**local, "KEY_PREFIX": "pleet"},
                "throttle": {**local, "LOCATION": "pleet-throttle", "KEY_PREFIX": "pleet"},
                "local": {**local, "LOCATION": "pleet-local", "KEY_PREFIX": "pleet"},
            }
        redis_cache = self._django_redis(db=1)
        return {
            # IGNORE_EXCEPTIONS: if Redis is unreachable, cache reads miss and writes no-op,
            # so requests fall through to PostgreSQL instead of failing.
            "default": {
                **redis_cache,
                "KEY_PREFIX": "pleet",
                "OPTIONS": {**redis_cache["OPTIONS"], "IGNORE_EXCEPTIONS": True},
            },
            # Throttles must NOT silently ignore errors (that would disable rate limiting);
            # apps.common.throttles falls back to the per-process "local" cache instead.
            "throttle": {**redis_cache, "KEY_PREFIX": "pleet"},
            "local": {**local, "LOCATION": "pleet-local", "KEY_PREFIX": "pleet"},
        }

    def _django_redis(self, db: int) -> dict:
        options: dict = {
            "SOCKET_CONNECT_TIMEOUT": self.socket_timeout,
            "SOCKET_TIMEOUT": self.socket_timeout,
        }
        if self.password:
            options["PASSWORD"] = self.password
        if self.mode == "sentinel":
            options |= {
                "CLIENT_CLASS": "django_redis.client.SentinelClient",
                "CONNECTION_POOL_CLASS": "redis.sentinel.SentinelConnectionPool",
                "SENTINELS": self.sentinels,
                "SENTINEL_KWARGS": {"password": self.password} if self.password else {},
            }
            location = f"redis://{self.master_name}/{db}"
        else:
            options["CLIENT_CLASS"] = "django_redis.client.DefaultClient"
            location = f"{self.url.rstrip('/')}/{db}"
        return {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": location,
            "OPTIONS": options,
        }

    # --- Channels -------------------------------------------------------------------------

    def channel_layers(self) -> dict:
        if self.mode == "none":
            return {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
        if self.mode == "sentinel":
            host: dict | str = {
                "sentinels": self.sentinels,
                "master_name": self.master_name,
                "sentinel_kwargs": {"password": self.password} if self.password else {},
            }
            if self.password:
                host["password"] = self.password
        else:
            host = f"{self.url.rstrip('/')}/2"
        return {
            "default": {
                "BACKEND": "channels_redis.core.RedisChannelLayer",
                "CONFIG": {"hosts": [host], "prefix": "pleet:channels", "capacity": 1500},
            }
        }

    # --- Celery ---------------------------------------------------------------------------

    def celery_broker(self) -> tuple[str, dict]:
        """(broker_url, transport_options)."""
        if self.mode == "sentinel":
            auth = f":{self.password}@" if self.password else ""
            url = ";".join(f"sentinel://{auth}{h}:{p}/0" for h, p in self.sentinels)
            options = {"master_name": self.master_name, "socket_timeout": 1}
            if self.password:
                options["sentinel_kwargs"] = {"password": self.password}
            return url, options
        if self.mode == "single":
            return f"{self.url.rstrip('/')}/0", {}
        return "memory://", {}
