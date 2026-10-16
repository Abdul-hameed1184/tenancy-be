import pytest
from django.conf import settings
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import AuthSession, User
from apps.accounts.services import make_reset_token
from apps.agents.models import AgentProfile
from apps.audit.models import AuditLog
from tests.factories import DEFAULT_PASSWORD, AgentFactory, UserFactory

pytestmark = pytest.mark.django_db

API = "/api/v1"
COOKIE = settings.AUTH_REFRESH_COOKIE["key"]
USER_KEYS = {"id", "name", "email", "role", "createdAt", "emailVerified"}
STRONG = "Tr1cky-Passphrase!"


def register(client, **overrides):
    body = {"role": "tenant", "name": "Ada Obi", "email": "ada@example.com", "password": STRONG}
    body.update(overrides)
    return client.post(f"{API}/auth/register", body, format="json")


def login(client, email, password=DEFAULT_PASSWORD, role=None):
    body = {"email": email, "password": password}
    if role:
        body["role"] = role
    return client.post(f"{API}/auth/login", body, format="json")


def refresh(client, **headers):
    headers.setdefault("HTTP_X_REQUESTED_WITH", "XMLHttpRequest")
    return client.post(f"{API}/auth/refresh", **headers)


# --- Register -------------------------------------------------------------------------------


def test_register_returns_contract_shape_and_working_token(api_client):
    response = register(api_client)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"user", "token"}
    assert set(body["user"]) == USER_KEYS  # empty optional avatarUrl/phone are omitted
    assert body["user"]["role"] == "tenant"
    assert body["user"]["createdAt"].endswith("Z")

    me = api_client.get(f"{API}/auth/me", HTTP_AUTHORIZATION=f"Bearer {body['token']}")
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"


def test_register_sets_httponly_refresh_cookie_scoped_to_auth(api_client):
    response = register(api_client)
    cookie = response.cookies[COOKIE]
    assert cookie["httponly"]
    assert cookie["path"] == "/api/v1/auth/"
    assert cookie["samesite"] == "Lax"
    assert "refresh" not in response.json()  # never exposed to JavaScript


def test_register_agent_creates_profile_and_returns_agent_shape(api_client):
    response = register(api_client, role="agent", email="agent@example.com")

    assert response.status_code == 201
    user = response.json()["user"]
    assert user["verificationStatus"] == "unverified"
    assert user["trustScore"] == 0
    assert user["assetsManagedCount"] == 0
    assert AgentProfile.objects.filter(user__email="agent@example.com").exists()


def test_cannot_self_register_as_admin(api_client):
    response = register(api_client, role="admin")
    assert response.status_code == 400
    assert response.json()["message"].startswith("Role:")
    assert not User.objects.exists()


def test_register_rejects_duplicate_email_case_insensitively(api_client):
    UserFactory(email="ada@example.com")
    response = register(api_client, email="ADA@Example.com")
    assert response.status_code == 400
    assert response.json()["message"] == "Email: A user with this email already exists."


def test_register_rejects_weak_password(api_client):
    response = register(api_client, password="12345678")
    assert response.status_code == 400
    assert "password" in response.json()["errors"]


def test_register_is_audited_without_secrets(api_client):
    register(api_client)
    entry = AuditLog.objects.get(action="USER_REGISTERED")
    assert entry.actor.email == "ada@example.com"
    assert STRONG not in str(entry.metadata)


# --- Login ----------------------------------------------------------------------------------


def test_login_success_is_case_insensitive_on_email(api_client):
    UserFactory(email="ada@example.com")
    response = login(api_client, "ADA@example.com", role="tenant")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "ada@example.com"
    assert COOKIE in response.cookies
    assert AuditLog.objects.filter(action="LOGIN").count() == 1


@pytest.mark.parametrize(
    ("email", "password", "role"),
    [
        ("ada@example.com", "wrong-password", "tenant"),  # bad password
        ("nobody@example.com", DEFAULT_PASSWORD, "tenant"),  # unknown account
    ],
)
def test_login_failures_share_one_generic_401(api_client, email, password, role):
    UserFactory(email="ada@example.com", role="tenant")
    response = login(api_client, email, password, role)
    assert response.status_code == 401
    assert response.json() == {"message": "Invalid email or password."}
    assert AuditLog.objects.filter(action="LOGIN_FAILED").count() == 1


def test_login_ignores_role_tab_and_returns_real_role(api_client):
    UserFactory(email="ada@example.com", role="tenant")
    response = login(api_client, "ada@example.com", role="landlord")
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "tenant"  # the frontend routes by this


def test_inactive_user_cannot_login(api_client):
    UserFactory(email="ada@example.com", is_active=False)
    assert login(api_client, "ada@example.com").status_code == 401


def test_login_ignores_stale_authorization_header(api_client):
    UserFactory(email="ada@example.com")
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    assert login(api_client, "ada@example.com").status_code == 200


def test_login_is_throttled_per_ip_and_email(api_client):
    UserFactory(email="ada@example.com")
    for _ in range(5):
        login(api_client, "ada@example.com", "wrong")
    assert login(api_client, "ada@example.com").status_code == 429
    # A different account from the same IP is unaffected.
    UserFactory(email="bob@example.com")
    assert login(api_client, "bob@example.com").status_code == 200


# --- Me / token validation ------------------------------------------------------------------


def test_me_requires_authentication(api_client):
    response = api_client.get(f"{API}/auth/me")
    assert response.status_code == 401
    assert "message" in response.json()


def test_me_rejects_garbage_token(api_client):
    response = api_client.get(f"{API}/auth/me", HTTP_AUTHORIZATION="Bearer abc.def.ghi")
    assert response.status_code == 401


def test_me_for_agent_returns_profile_in_two_queries(
    api_client, authenticate, django_assert_num_queries
):
    agent = AgentFactory()
    authenticate(api_client, agent)
    # 1: session + user + agent profile, joined. 2: COUNT of active assignments.
    with django_assert_num_queries(2):
        response = api_client.get(f"{API}/auth/me")
    assert response.status_code == 200
    assert response.json()["agency"] == "Lagos Homes Ltd"


def test_access_token_of_inactive_user_is_rejected(api_client, authenticate):
    user = UserFactory()
    authenticate(api_client, user)
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert api_client.get(f"{API}/auth/me").status_code == 401


# --- Logout ---------------------------------------------------------------------------------


def test_logout_revokes_session_so_access_token_stops_working(api_client, authenticate):
    user = UserFactory()
    issued = authenticate(api_client, user)

    response = api_client.post(f"{API}/auth/logout")
    assert response.status_code == 204
    assert response.cookies[COOKIE].value == ""  # cookie cleared

    issued.session.refresh_from_db()
    assert issued.session.revoke_reason == "logout"
    assert api_client.get(f"{API}/auth/me").status_code == 401


def test_logout_only_ends_the_current_session(api_client, authenticate):
    user = UserFactory()
    other_device = authenticate(APIClient(), user)
    authenticate(api_client, user)
    api_client.post(f"{API}/auth/logout")
    other_device.session.refresh_from_db()
    assert other_device.session.revoked_at is None


# --- Refresh rotation -----------------------------------------------------------------------


def test_refresh_rotates_cookie_and_returns_new_access_token(api_client):
    UserFactory(email="ada@example.com")
    first_cookie = login(api_client, "ada@example.com").cookies[COOKIE].value

    response = refresh(api_client)

    assert response.status_code == 200
    new_cookie = response.cookies[COOKIE].value
    assert new_cookie and new_cookie != first_cookie
    me = api_client.get(f"{API}/auth/me", HTTP_AUTHORIZATION=f"Bearer {response.json()['token']}")
    assert me.status_code == 200


def test_reusing_a_rotated_refresh_token_revokes_the_whole_session(api_client):
    UserFactory(email="ada@example.com")
    stolen = login(api_client, "ada@example.com").cookies[COOKIE].value
    legit = refresh(api_client)  # legitimate client rotates; `stolen` is now stale
    assert legit.status_code == 200

    api_client.cookies[COOKIE] = stolen  # attacker replays the old token
    replay = refresh(api_client)

    assert replay.status_code == 401
    session = AuthSession.objects.get()
    assert session.revoke_reason == "reuse_detected"
    assert AuditLog.objects.filter(action="TOKEN_REUSE_DETECTED").exists()
    # The legitimate client's fresh tokens die with the session too.
    me = api_client.get(f"{API}/auth/me", HTTP_AUTHORIZATION=f"Bearer {legit.json()['token']}")
    assert me.status_code == 401


def test_refresh_without_cookie_is_401(api_client):
    assert refresh(api_client).status_code == 401


def test_refresh_without_csrf_header_is_403(api_client):
    UserFactory(email="ada@example.com")
    login(api_client, "ada@example.com")
    response = api_client.post(f"{API}/auth/refresh")
    assert response.status_code == 403


def test_refresh_after_logout_is_401(api_client):
    UserFactory(email="ada@example.com")
    logged_in = login(api_client, "ada@example.com")
    refresh_cookie = logged_in.cookies[COOKIE].value
    api_client.post(f"{API}/auth/logout", HTTP_AUTHORIZATION=f"Bearer {logged_in.json()['token']}")
    api_client.cookies[COOKIE] = refresh_cookie  # replay the cookie logout cleared
    assert refresh(api_client).status_code == 401


# --- Password reset -------------------------------------------------------------------------


def test_forgot_password_for_unknown_email_is_204_and_sends_nothing(api_client):
    response = api_client.post(
        f"{API}/auth/forgot-password", {"email": "ghost@example.com"}, format="json"
    )
    assert response.status_code == 204
    assert mail.outbox == []


def test_forgot_password_emails_frontend_reset_link(api_client):
    UserFactory(email="ada@example.com")
    response = api_client.post(
        f"{API}/auth/forgot-password", {"email": "ada@example.com"}, format="json"
    )
    assert response.status_code == 204
    assert len(mail.outbox) == 1
    assert f"{settings.FRONTEND_URL}/auth/reset-password?token=" in mail.outbox[0].body
    assert len(mail.outbox[0].alternatives) == 1
    assert "Reset password" in mail.outbox[0].alternatives[0].content
    reset_url = f"{settings.FRONTEND_URL}/auth/reset-password?token="
    assert reset_url in mail.outbox[0].alternatives[0].content


def test_reset_password_changes_password_and_revokes_sessions(api_client, authenticate):
    user = UserFactory(email="ada@example.com")
    issued = authenticate(APIClient(), user)  # a session on another device
    token = make_reset_token(user)

    response = api_client.post(
        f"{API}/auth/reset-password", {"token": token, "password": STRONG}, format="json"
    )

    assert response.status_code == 204
    user.refresh_from_db()
    assert user.check_password(STRONG)
    issued.session.refresh_from_db()
    assert issued.session.revoke_reason == "password_reset"
    assert login(api_client, "ada@example.com", STRONG).status_code == 200


def test_reset_token_is_single_use(api_client):
    user = UserFactory()
    token = make_reset_token(user)
    body = {"token": token, "password": STRONG}
    assert api_client.post(f"{API}/auth/reset-password", body, format="json").status_code == 204
    second = api_client.post(
        f"{API}/auth/reset-password", {"token": token, "password": "An0ther-Pass!"}, format="json"
    )
    assert second.status_code == 400
    assert second.json()["message"] == "Token: This reset link is invalid or has expired."


@pytest.mark.parametrize("token", ["garbage", "abc.def", "Zm9v.bar-baz"])
def test_reset_rejects_malformed_tokens(api_client, token):
    response = api_client.post(
        f"{API}/auth/reset-password", {"token": token, "password": STRONG}, format="json"
    )
    assert response.status_code == 400


def test_reset_rejects_weak_password_under_password_field(api_client):
    token = make_reset_token(UserFactory())
    response = api_client.post(
        f"{API}/auth/reset-password", {"token": token, "password": "123"}, format="json"
    )
    assert response.status_code == 400
    assert "password" in response.json()["errors"]


# --- Profile --------------------------------------------------------------------------------


def test_user_can_update_own_name_and_phone_only(api_client, authenticate):
    user = UserFactory(role="tenant")
    authenticate(api_client, user)

    response = api_client.patch(
        f"{API}/users/{user.id}",
        {"id": str(user.id), "name": "New Name", "phone": "+2348000000000", "role": "admin"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"
    assert response.json()["phone"] == "+2348000000000"
    user.refresh_from_db()
    assert user.role == "tenant"  # not editable through this endpoint


def test_user_cannot_update_someone_else(api_client, authenticate):
    me, other = UserFactory(), UserFactory()
    authenticate(api_client, me)
    response = api_client.patch(f"{API}/users/{other.id}", {"name": "Hacked"}, format="json")
    assert response.status_code == 403
    other.refresh_from_db()
    assert other.name != "Hacked"


def test_profile_update_requires_auth(api_client):
    user = UserFactory()
    response = api_client.patch(f"{API}/users/{user.id}", {"name": "x"}, format="json")
    assert response.status_code == 401


# --- Realtime ticket ------------------------------------------------------------------------


def test_realtime_ticket_requires_auth_and_is_opaque(api_client, authenticate):
    assert api_client.post(f"{API}/realtime/ticket").status_code == 401
    issued = authenticate(api_client, UserFactory())
    body = api_client.post(f"{API}/realtime/ticket").json()
    assert body["expiresIn"] == 30
    assert issued.access not in body["ticket"]  # never the JWT itself


def test_ticket_dies_with_its_session(api_client, authenticate):
    from apps.accounts import realtime

    user = UserFactory()
    authenticate(api_client, user)
    ticket = api_client.post(f"{API}/realtime/ticket").json()["ticket"]
    api_client.post(f"{API}/auth/logout")
    assert realtime.redeem_ticket(ticket) is None
