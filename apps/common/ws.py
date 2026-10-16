"""WebSocket plumbing shared by every consumer."""

import logging
from urllib.parse import parse_qs

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)

# Custom close codes (4000-4999 are reserved for applications).
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403


def thread_group(thread_id) -> str:
    # Channel group names allow only ASCII letters, digits, hyphens, underscores, periods.
    return f"pleet.thread.{thread_id}"


def user_group(user_id) -> str:
    return f"pleet.user.{user_id}"


class TicketAuthMiddleware:
    """Resolves ?ticket=... into scope["user"] (AnonymousUser when missing/invalid)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        from apps.accounts.realtime import redeem_ticket

        params = parse_qs(scope.get("query_string", b"").decode())
        ticket = (params.get("ticket") or [None])[0]
        user = await database_sync_to_async(redeem_ticket)(ticket)
        scope = {**scope, "user": user or AnonymousUser()}
        return await self.app(scope, receive, send)


def broadcast(group: str, message: dict) -> bool:
    """
    Best-effort fan-out from synchronous code (services, event handlers, Celery tasks).

    Realtime delivery is a convenience layered on top of durable state: the message or
    notification is already committed to PostgreSQL, and clients re-fetch over REST on
    reconnect. So a channel-layer outage (e.g. during a Redis failover) is logged, not
    raised, and never fails or retries the business operation.
    """
    layer = get_channel_layer()
    if layer is None:
        return False
    try:
        async_to_sync(layer.group_send)(group, message)
    except Exception:
        logger.warning("Realtime broadcast failed", extra={"group": group}, exc_info=True)
        return False
    return True
