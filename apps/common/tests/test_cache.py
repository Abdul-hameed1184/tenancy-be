import pytest
from django.core.cache import cache, caches

from apps.common import cache as versioned
from tests.factories import AgentFactory, AssignmentFactory, PropertyFactory, UserFactory

pytestmark = pytest.mark.django_db
API = "/api/v1"


def test_version_starts_at_one_and_bump_increments():
    assert versioned.namespace_version("things") == 1
    versioned.bump("things")
    assert versioned.namespace_version("things") == 2


def test_bump_recovers_when_version_key_was_evicted():
    cache.delete("cache:things:version")
    versioned.bump("things")
    assert versioned.namespace_version("things") == 2


def test_bump_changes_every_key_in_the_namespace():
    before = versioned.make_key("things", "list", {"a": "1"})
    versioned.bump("things")
    assert versioned.make_key("things", "list", {"a": "1"}) != before


def test_key_is_independent_of_param_order():
    assert versioned.make_key("t", "l", {"a": "1", "b": "2"}) == versioned.make_key(
        "t", "l", {"b": "2", "a": "1"}
    )


def test_property_list_cache_hit_costs_no_queries(api_client, django_assert_num_queries):
    PropertyFactory.create_batch(3)
    first = api_client.get(f"{API}/properties").json()
    with django_assert_num_queries(0):
        second = api_client.get(f"{API}/properties").json()
    assert first == second


def test_different_filters_are_cached_separately(api_client):
    PropertyFactory(city="Lagos")
    PropertyFactory(city="Abuja")
    assert len(api_client.get(f"{API}/properties", {"city": "Lagos"}).json()) == 1
    assert len(api_client.get(f"{API}/properties").json()) == 2


def test_invalid_filters_are_never_cached(api_client):
    assert api_client.get(f"{API}/properties", {"status": "bogus"}).status_code == 400
    assert api_client.get(f"{API}/properties", {"status": "bogus"}).status_code == 400


def test_landlord_edit_invalidates_after_commit(
    api_client, authenticate, django_capture_on_commit_callbacks
):
    prop = PropertyFactory(title="Old title")
    assert api_client.get(f"{API}/properties").json()[0]["title"] == "Old title"

    owner_client = api_client.__class__()
    authenticate(owner_client, prop.landlord)
    with django_capture_on_commit_callbacks(execute=True):
        owner_client.patch(f"{API}/properties/{prop.id}", {"title": "New title"}, format="json")

    assert api_client.get(f"{API}/properties").json()[0]["title"] == "New title"
    assert api_client.get(f"{API}/properties/{prop.id}").json()["title"] == "New title"


def test_assignment_invalidates_properties_and_agent_cards(
    api_client, authenticate, django_capture_on_commit_callbacks
):
    prop, agent = PropertyFactory(), AgentFactory()
    assert api_client.get(f"{API}/agents/{agent.id}").json()["assetsManagedCount"] == 0
    assert api_client.get(f"{API}/properties/{prop.id}").json()["agentId"] is None

    owner_client = api_client.__class__()
    authenticate(owner_client, prop.landlord)
    with django_capture_on_commit_callbacks(execute=True):
        owner_client.put(
            f"{API}/properties/{prop.id}/agent", {"agentId": str(agent.id)}, format="json"
        )

    assert api_client.get(f"{API}/agents/{agent.id}").json()["assetsManagedCount"] == 1
    assert api_client.get(f"{API}/properties/{prop.id}").json()["agentId"] == str(agent.id)


def test_cached_agent_rows_are_still_redacted_per_viewer(api_client, authenticate):
    AssignmentFactory()
    agent = AgentFactory()
    agent.agent_profile.passport_doc_url = "https://docs.example.com/p.pdf"
    agent.agent_profile.save()
    authenticate(api_client, agent)
    assert api_client.get(f"{API}/agents/{agent.id}").json()["passportDocUrl"]
    public = api_client.__class__()
    assert "passportDocUrl" not in public.get(f"{API}/agents/{agent.id}").json()


def test_login_throttle_survives_a_redis_outage(api_client, monkeypatch):
    """Primary throttle cache throwing must not disable brute-force protection."""
    broken = caches["throttle"]

    def explode(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(broken, "get", explode)
    monkeypatch.setattr(broken, "set", explode)
    UserFactory(email="ada@example.com")
    body = {"email": "ada@example.com", "password": "wrong"}
    for _ in range(5):
        assert api_client.post(f"{API}/auth/login", body, format="json").status_code == 401
    assert api_client.post(f"{API}/auth/login", body, format="json").status_code == 429
