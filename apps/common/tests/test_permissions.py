import pytest

from apps.accounts import services
from apps.common.permissions import HasRole, IsLandlord
from tests.factories import UserFactory

pytestmark = [pytest.mark.django_db, pytest.mark.urls("apps.common.tests.permission_urls")]

ROLES = ["admin", "landlord", "agent", "tenant"]

# endpoint -> roles that may call it. Every other role gets 403, anonymous gets 401.
ROLE_MATRIX = {
    "/admin-only": {"admin"},
    "/landlord-only": {"landlord"},
    "/agent-only": {"agent"},
    "/tenant-only": {"tenant"},
    "/agent-or-tenant": {"agent", "tenant"},
}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("path", "allowed"), ROLE_MATRIX.items())
def test_role_matrix(api_client, authenticate, path, allowed, role):
    authenticate(api_client, UserFactory(role=role))
    response = api_client.get(path)
    if role in allowed:
        assert response.status_code == 200
    else:
        assert response.status_code == 403
        assert response.json()["message"].startswith("This action is only available to")


@pytest.mark.parametrize("path", ROLE_MATRIX)
def test_anonymous_gets_401_not_403(api_client, path):
    # 401 is what makes the frontend redirect to login; 403 would just show an error toast.
    assert api_client.get(path).status_code == 401


def test_role_denial_message_names_the_roles(api_client, authenticate):
    authenticate(api_client, UserFactory(role="landlord"))
    response = api_client.get("/agent-or-tenant")
    assert response.json() == {"message": "This action is only available to agents or tenants."}


def test_has_role_rejects_unknown_roles():
    with pytest.raises(ValueError):
        HasRole("superuser")


def test_role_permissions_are_reusable_classes():
    assert IsLandlord.roles == frozenset({"landlord"})
    assert HasRole("agent", "tenant").roles == frozenset({"agent", "tenant"})


# --- Scope (layer 2) ------------------------------------------------------------------------


def test_list_only_returns_rows_in_scope(api_client, authenticate):
    me, _other = UserFactory(), UserFactory()
    authenticate(api_client, me)
    assert [u["id"] for u in api_client.get("/users").json()] == [str(me.id)]


def test_row_outside_scope_is_404_not_403(api_client, authenticate):
    me, other = UserFactory(), UserFactory()
    authenticate(api_client, me)
    response = api_client.get(f"/users/{other.id}")
    assert response.status_code == 404  # existence of `other` is not revealed


def test_query_filter_cannot_widen_scope(api_client, authenticate):
    """A forged ?userId=<someone else> narrows within scope -> empty, never their data."""
    me, other = UserFactory(), UserFactory()
    authenticate(api_client, me)
    assert api_client.get("/users", {"userId": str(other.id)}).json() == []
    assert len(api_client.get("/users", {"userId": str(me.id)}).json()) == 1


def test_admin_scope_sees_everyone(api_client, authenticate):
    UserFactory.create_batch(2)
    authenticate(api_client, UserFactory(role="admin"))
    assert len(api_client.get("/users").json()) == 3


# --- Object permission (layer 3) ------------------------------------------------------------


def test_owner_can_modify_own_object(api_client, authenticate):
    me = UserFactory()
    issued = authenticate(api_client, me)
    response = api_client.patch(
        f"/sessions/{issued.session.id}", {"user_agent": "renamed"}, format="json"
    )
    assert response.status_code == 200


def test_non_owner_is_forbidden(api_client, authenticate):
    victim_session = services.start_session(UserFactory()).session
    authenticate(api_client, UserFactory())
    response = api_client.patch(
        f"/sessions/{victim_session.id}", {"user_agent": "pwned"}, format="json"
    )
    assert response.status_code == 403
    victim_session.refresh_from_db()
    assert victim_session.user_agent != "pwned"


# --- Client-supplied identity ---------------------------------------------------------------


def test_ensure_self_rejects_someone_elses_id(api_client, authenticate):
    me, other = UserFactory(), UserFactory()
    authenticate(api_client, me)
    assert api_client.get("/self-only", {"userId": str(other.id)}).status_code == 403
    assert api_client.get("/self-only", {"userId": str(me.id)}).status_code == 200
    assert api_client.get("/self-only").status_code == 200  # omitted -> defaults to self


def test_ensure_self_lets_admin_act_for_others_when_allowed(api_client, authenticate):
    other = UserFactory()
    authenticate(api_client, UserFactory(role="admin"))
    assert api_client.get("/self-only", {"userId": str(other.id)}).status_code == 200
