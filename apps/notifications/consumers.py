"""
ws://<host>/ws/notifications/?ticket=<ticket>

Server -> client: {"type": "notification.created", "notification": <Notification>}

Each user's sockets (any tab, any device, any server process) join pleet.user.<id>, so a
notification created anywhere reaches all of them through the channel layer.
"""

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.common.ws import CLOSE_UNAUTHENTICATED, user_group


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        self.group = user_group(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Push-only: reads and acknowledgements go through REST.
        await self.send_json({"type": "error", "message": "This socket is receive-only."})

    async def notification_created(self, event):
        await self.send_json(
            {"type": "notification.created", "notification": event["notification"]}
        )
