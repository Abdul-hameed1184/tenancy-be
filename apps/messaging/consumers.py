"""
Realtime chat: ws://<host>/ws/threads/<thread_id>/?ticket=<ticket>

Client -> server
    {"type": "message.send", "body": "Hello"}
Server -> client
    {"type": "message.created", "message": <Message>}   every participant, including sender
    {"type": "error", "message": "..."}                  only to the offending socket

Lifecycle:
    connect     ticket (middleware) -> authenticated? -> participant? -> join group -> accept
    receive     validate -> messaging.services.send_message (same path as REST)
                -> commit -> MessageSent handler -> group_send to every participant
    disconnect  leave group

The consumer holds no business rules: validation is the REST serializer, persistence and
authorization are the messaging service, and fan-out is the MessageSent event handler.
"""

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.common.ws import CLOSE_FORBIDDEN, CLOSE_UNAUTHENTICATED, thread_group

from . import selectors, services
from .serializers import SendMessageSerializer

logger = logging.getLogger(__name__)


class ThreadConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.thread_id = self.scope["url_route"]["kwargs"]["thread_id"]
        self.group = thread_group(self.thread_id)

        if not self.user.is_authenticated:
            logger.info("WS refused: unauthenticated", extra={"thread_id": str(self.thread_id)})
            await self.close(code=CLOSE_UNAUTHENTICATED)  # handshake refused, never accepted
            return
        if not await database_sync_to_async(selectors.is_participant)(self.user.pk, self.thread_id):
            logger.warning(
                "WS refused: not a participant",
                extra={"thread_id": str(self.thread_id), "user_id": str(self.user.pk)},
            )
            await self.close(code=CLOSE_FORBIDDEN)
            return

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or content.get("type") != "message.send":
            await self.send_json({"type": "error", "message": "Unsupported message type."})
            return
        body = SendMessageSerializer(data={"body": content.get("body")})
        if not body.is_valid():
            await self.send_json({"type": "error", "message": "Message body is invalid."})
            return
        try:
            await database_sync_to_async(services.send_message)(
                thread_id=self.thread_id, sender=self.user, body=body.validated_data["body"]
            )
        except services.NotParticipant:
            # Membership is rechecked on every send: someone removed mid-conversation
            # can't keep posting through an already-open socket.
            await self.send_json({"type": "error", "message": "You left this thread."})
            await self.close(code=CLOSE_FORBIDDEN)

    # Group message handler: `type: "message.created"` dispatches here.
    async def message_created(self, event):
        await self.send_json({"type": "message.created", "message": event["message"]})
