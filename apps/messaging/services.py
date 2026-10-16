from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.accounts.models import User
from apps.common.events import publish

from .events import MessageSent
from .models import Message, MessageThread, ThreadParticipant


class NotParticipant(Exception):
    pass


def start_thread(*, user: User, recipient_id, property_id) -> MessageThread:
    from . import selectors

    recipient = User.objects.filter(pk=recipient_id, is_active=True).first()
    if recipient is None or not selectors.can_start_thread(
        user=user, recipient_id=recipient_id, property_id=property_id
    ):
        raise NotParticipant
    pair = ":".join(sorted((str(user.pk), str(recipient.pk)))) + f":{property_id}"
    with transaction.atomic():
        thread, _ = MessageThread.objects.get_or_create(
            contact_pair=pair,
            defaults={"property_id": property_id, "last_message_at": timezone.now()},
        )
        ThreadParticipant.objects.get_or_create(thread=thread, user=user)
        ThreadParticipant.objects.get_or_create(thread=thread, user=recipient)
    return thread


def initialize_contact_threads(*, user: User) -> None:
    """Create one empty thread for every current contact/property relationship."""
    from . import selectors

    contacts = selectors.primary_contacts_for(user)
    now = timezone.now()
    with transaction.atomic():
        for contact in contacts:
            recipient_id = contact["id"]
            if recipient_id == str(user.pk):
                continue
            recipient = User.objects.filter(pk=recipient_id, is_active=True).only("pk").first()
            if recipient is None:
                continue

            pair = ":".join(sorted((str(user.pk), str(recipient.pk)))) + f":{contact['propertyId']}"
            thread, _ = MessageThread.objects.get_or_create(
                contact_pair=pair,
                defaults={
                    "property_id": contact["propertyId"],
                    "last_message_at": now,
                },
            )
            ThreadParticipant.objects.get_or_create(thread=thread, user=user)
            ThreadParticipant.objects.get_or_create(thread=thread, user=recipient)


def send_message(*, thread_id, sender: User, body: str) -> Message:
    """
    Persist a message and bump the thread's activity timestamp.

    Used by both the REST endpoint and the WebSocket consumer, so the rules can't diverge.
    Membership is checked on every send (not just when a socket connects), so removing a
    participant takes effect immediately.

    No row lock: last_message_at is advanced with a single
    UPDATE ... SET last_message_at = GREATEST(last_message_at, %s), which PostgreSQL applies
    atomically, and GREATEST keeps it from going backwards when two sends commit out of
    order.
    """
    body = body.strip()
    with transaction.atomic():
        if not ThreadParticipant.objects.filter(thread_id=thread_id, user=sender).exists():
            raise NotParticipant
        recipient_ids = list(
            ThreadParticipant.objects.filter(thread_id=thread_id)
            .exclude(user_id=sender.pk)
            .values_list("user_id", flat=True)
        )
        message = Message.objects.create(thread_id=thread_id, sender=sender, body=body)
        MessageThread.objects.filter(pk=thread_id).update(
            last_message_at=Greatest(F("last_message_at"), Value(message.sent_at))
        )
        publish(
            MessageSent(
                message_id=str(message.pk),
                thread_id=str(thread_id),
                sender_id=str(sender.pk),
                recipient_ids=[str(r) for r in recipient_ids],
            )
        )
    return message


def mark_thread_read(*, thread_id, user: User) -> None:
    """Advance this participant's read cursor without affecting other participants."""
    now = timezone.now()
    updated = ThreadParticipant.objects.filter(thread_id=thread_id, user=user).update(
        last_read_at=now
    )
    if not updated:
        raise NotParticipant
