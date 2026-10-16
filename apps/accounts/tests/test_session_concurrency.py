import threading

import pytest
from django.db import connection

from apps.accounts import services
from apps.accounts.models import AuthSession
from tests.factories import UserFactory


@pytest.mark.django_db(transaction=True)
def test_concurrent_refresh_with_same_token_cannot_yield_two_live_tokens():
    """
    Without SELECT ... FOR UPDATE both threads could read the same current_jti, both pass
    the check and both mint a valid refresh token, forking one session into two. With the
    lock, the second thread waits, then sees the jti already swapped and treats it as reuse.
    """
    user = UserFactory()
    raw = services.start_session(user).refresh
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker():
        try:
            barrier.wait()
            services.rotate_session(raw)
            outcomes.append("rotated")
        except services.AuthError:
            outcomes.append("rejected")
        finally:
            connection.close()  # each thread owns its own DB connection

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["rejected", "rotated"]
    session = AuthSession.objects.get()
    assert session.revoke_reason == AuthSession.RevokeReason.REUSE_DETECTED
