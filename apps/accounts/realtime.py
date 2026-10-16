"""
WebSocket authentication with single-use tickets.

Browsers can't attach an Authorization header to `new WebSocket(url)`, and putting the JWT
in the URL would leak a 60-minute credential into proxy and access logs. Instead:

1. The client calls POST /api/v1/realtime/ticket with its Bearer token.
2. It receives an opaque random ticket, valid for WS_TICKET_TTL_SECONDS (30s), usable once.
3. It connects to ws://.../ws/threads/<id>/?ticket=<ticket>.

Only sha256(ticket) is stored. Redemption is "get, then delete": the delete reports
whether this caller removed the key, so of two concurrent redemptions exactly one wins. A
ticket seen in a log is useless seconds later. The ticket is bound to the auth session
that minted it, so logging out also invalidates any ticket not yet used.
"""

import hashlib
import secrets

from django.conf import settings
from django.core.cache import cache

from .models import AuthSession, User


def _key(raw: str) -> str:
    return f"ws:ticket:{hashlib.sha256(raw.encode()).hexdigest()}"


def issue_ticket(user: User) -> str:
    raw = secrets.token_urlsafe(32)
    cache.set(
        _key(raw),
        {"user_id": str(user.pk), "session_id": str(getattr(user, "auth_session_id", ""))},
        timeout=settings.WS_TICKET_TTL_SECONDS,
    )
    return raw


def redeem_ticket(raw: str | None) -> User | None:
    if not raw or len(raw) > 128:
        return None
    key = _key(raw)
    data = cache.get(key)
    if not data or not cache.delete(key):
        return None  # unknown, expired, or someone else redeemed it first
    session = (
        AuthSession.objects.active()
        .select_related("user")
        .filter(id=data["session_id"], user_id=data["user_id"], user__is_active=True)
        .first()
    )
    return session.user if session else None
