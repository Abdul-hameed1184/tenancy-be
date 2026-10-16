from types import SimpleNamespace

import pytest

from apps.common.request import client_ip, user_agent
from apps.common.views import server_error


def req(remote="10.0.0.1", xff=None, ua=None):
    meta = {"REMOTE_ADDR": remote}
    if xff:
        meta["HTTP_X_FORWARDED_FOR"] = xff
    if ua:
        meta["HTTP_USER_AGENT"] = ua
    return SimpleNamespace(META=meta)


def test_without_trusted_proxies_x_forwarded_for_is_ignored(settings):
    """Otherwise any client could spoof its IP and dodge per-IP throttles."""
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": None}
    assert client_ip(req(xff="6.6.6.6")) == "10.0.0.1"


@pytest.mark.parametrize(
    ("num_proxies", "xff", "expected"),
    [
        (1, "203.0.113.9", "203.0.113.9"),
        # Client forged a header; our single proxy appended the real address on the right.
        (1, "6.6.6.6, 203.0.113.9", "203.0.113.9"),
        (2, "6.6.6.6, 203.0.113.9, 10.1.1.1", "203.0.113.9"),
        (3, "203.0.113.9", "203.0.113.9"),  # fewer hops than configured: take the leftmost
    ],
)
def test_trusted_proxies_pick_the_right_hop(settings, num_proxies, xff, expected):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": num_proxies}
    assert client_ip(req(xff=xff)) == expected


def test_user_agent_is_truncated():
    assert len(user_agent(req(ua="x" * 1000))) == 256


def test_server_error_never_leaks_details():
    response = server_error(None)
    assert response.status_code == 500
    assert response.content == b'{"message": "Something went wrong. Please try again."}'
