"""
Against a real Redis (skipped unless PLEET_TEST_REDIS_URL is set; CI sets it).

The rest of the suite uses in-process stand-ins; these tests prove the production
backends configured by RedisTopology actually work: django-redis cache, the throttle
alias, and the channels-redis layer (group fan-out across "processes").
"""

import contextlib
import os
import uuid

import pytest
from django.core.cache import caches
from django.core.cache.backends.base import InvalidCacheBackendError
from django.test import override_settings

from config.settings.redis_topology import RedisTopology

REDIS_URL = os.environ.get("PLEET_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="set PLEET_TEST_REDIS_URL to run")


@pytest.fixture
def real_redis():
    topology = RedisTopology(url=REDIS_URL)
    with override_settings(CACHES=topology.caches(), CHANNEL_LAYERS=topology.channel_layers()):
        for alias in ("default", "throttle"):
            with contextlib.suppress(InvalidCacheBackendError):
                caches[alias].close()
        yield topology


def test_cache_round_trip_with_ttl(real_redis):
    cache = caches["default"]
    key = f"it:{uuid.uuid4()}"
    cache.set(key, {"n": 1}, timeout=30)
    assert cache.get(key) == {"n": 1}
    assert cache.delete(key) is True
    assert cache.delete(key) is False  # what single-use WS tickets rely on


def test_versioned_namespace_on_real_redis(real_redis):
    from apps.common import cache as versioned

    namespace = f"it-{uuid.uuid4().hex[:8]}"
    assert versioned.namespace_version(namespace) == 1
    versioned.bump(namespace)
    assert versioned.namespace_version(namespace) == 2


def test_unreachable_redis_degrades_to_cache_misses():
    broken = RedisTopology(url="redis://127.0.0.1:1")  # nothing listens on port 1
    with override_settings(CACHES=broken.caches()):
        cache = caches["default"]
        cache.set("k", "v")  # IGNORE_EXCEPTIONS: no error raised
        assert cache.get("k") is None


@pytest.mark.asyncio
async def test_channel_layer_group_fan_out(real_redis):
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    group = f"pleet.it.{uuid.uuid4().hex}"
    first, second = await layer.new_channel(), await layer.new_channel()
    await layer.group_add(group, first)
    await layer.group_add(group, second)

    await layer.group_send(group, {"type": "message.created", "body": "hi"})

    assert (await layer.receive(first))["body"] == "hi"
    assert (await layer.receive(second))["body"] == "hi"
    await layer.flush()
