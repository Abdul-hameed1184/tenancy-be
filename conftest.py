import pytest
from django.core.cache import caches
from rest_framework.test import APIClient

from apps.accounts import services
from tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    # Cached responses and throttle counters live in several cache aliases; isolate every
    # test from the previous one.
    for alias in caches:
        caches[alias].clear()
    yield
    for alias in caches:
        caches[alias].clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user_factory():
    return UserFactory


@pytest.fixture
def authenticate():
    """authenticate(client, user) -> SessionTokens; sets the Bearer header on the client."""

    def _authenticate(client: APIClient, user) -> services.SessionTokens:
        issued = services.start_session(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.access}")
        return issued

    return _authenticate
