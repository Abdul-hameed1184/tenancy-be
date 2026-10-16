from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel


class MessageThread(UUIDModel):
    property = models.ForeignKey(
        "properties.Property",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="message_threads",
    )
    contact_pair = models.CharField(max_length=300, unique=True, null=True, blank=True)
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ThreadParticipant", related_name="message_threads"
    )
    last_message_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-last_message_at"]
        indexes = [models.Index(fields=["-last_message_at"], name="msg_thread_recent_idx")]

    def __str__(self) -> str:
        return f"Thread {self.pk}"


class ThreadParticipant(models.Model):
    """
    Explicit through-model: membership is the authorization boundary for REST and WebSocket
    access, and it carries per-member state (joined_at, last_read_at).
    """

    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="thread_memberships"
    )
    joined_at = models.DateTimeField(default=timezone.now)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["thread", "user"], name="msg_one_membership"),
        ]
        indexes = [
            # "threads I'm in" and "am I in this thread?" are both (user, thread) lookups.
            models.Index(fields=["user", "thread"], name="msg_member_user_thread_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.thread_id}"


class Message(UUIDModel):
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_messages"
    )
    body = models.TextField(max_length=5000)
    sent_at = models.DateTimeField(default=timezone.now, editable=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sent_at"]
        indexes = [models.Index(fields=["thread", "sent_at"], name="msg_thread_sent_idx")]
        constraints = [
            models.CheckConstraint(condition=~models.Q(body=""), name="msg_body_not_empty"),
        ]

    def __str__(self) -> str:
        return f"Message {self.pk} in {self.thread_id}"
