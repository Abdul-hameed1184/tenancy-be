import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.urls("apps.common.tests.urls")
@pytest.mark.parametrize("path", ["/echo", "/echo/"])
def test_post_works_with_and_without_trailing_slash(api_client, path):
    response = api_client.post(path, {"a": 1}, format="json")
    assert response.status_code == 200  # no 301 redirect that would drop the body
    assert response.json() == {"received": {"a": 1}}


@pytest.mark.urls("apps.common.tests.urls")
@pytest.mark.parametrize("path", ["/items", "/items/", "/items/abc", "/items/abc/"])
def test_router_matches_with_and_without_trailing_slash(api_client, path):
    assert api_client.get(path).status_code == 200


def test_liveness_touches_no_dependencies(api_client, django_assert_num_queries):
    with django_assert_num_queries(0):
        response = api_client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_checks_database(api_client):
    response = api_client.get("/health/ready/")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "not_configured"},
    }


def test_redis_outage_degrades_but_does_not_fail_readiness(api_client, monkeypatch, settings):
    from apps.common import health
    from config.settings.redis_topology import RedisTopology

    settings.REDIS = RedisTopology(url="redis://unreachable:6379")

    def explode(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(health.caches["throttle"], "set", explode)
    response = api_client.get("/health/ready/")
    assert response.status_code == 200
    assert response.json()["checks"]["redis"] == "degraded"


def test_readiness_reports_503_when_database_is_down(api_client, monkeypatch):
    from apps.common import health

    monkeypatch.setattr(health, "_check_database", lambda: "error")
    response = api_client.get("/health/ready/")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_unknown_url_returns_json_404(api_client):
    response = api_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"message": "Not found."}


def test_openapi_schema_is_served(api_client):
    response = api_client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "PLEET API"
