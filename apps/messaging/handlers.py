from apps.common.events import subscribe
from apps.common.ws import broadcast, thread_group

from .events import MessageSent
from .models import Message
from .serializers import MessageSerializer


@subscribe(MessageSent)
def broadcast_message(event: MessageSent) -> None:
    """Push a committed message to every open socket on its thread (REST or WS origin)."""
    message = Message.objects.filter(pk=event.message_id).first()
    if message is None:
        return
    broadcast(
        thread_group(event.thread_id),
        {"type": "message.created", "message": MessageSerializer(message).data},
    )
