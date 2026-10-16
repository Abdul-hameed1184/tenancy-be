from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel


class Notification(UUIDModel):
    class Type(models.TextChoices):
        NEW_MESSAGE = "new_message", "New message"
        MAINTENANCE_REPORTED = "maintenance_reported", "Maintenance reported"
        MAINTENANCE_UPDATE = "maintenance_update", "Maintenance update"
        INSPECTION_REQUESTED = "inspection_requested", "Inspection requested"
        INSPECTION_CONFIRMED = "inspection_confirmed", "Inspection confirmed"
        INSPECTION_COMPLETED = "inspection_completed", "Inspection completed"
        INSPECTION_CANCELLED = "inspection_cancelled", "Inspection cancelled"
        PAYMENT_RECEIVED = "payment_received", "Payment received"
        PAYMENT_REMINDER = "payment_reminder", "Payment reminder"
        PAYMENT_OVERDUE = "payment_overdue", "Payment overdue"
        AGENT_VERIFICATION = "agent_verification", "Agent verification"
        PROPERTY_ASSIGNMENT = "property_assignment", "Property assignment"
        TENANT_ASSIGNMENT_REQUEST = "tenant_assignment_request", "Tenant assignment request"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=500)
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    # Idempotency key: the same cause (event id + recipient, or reminder + due date) can
    # only ever produce one notification, however often it is delivered.
    dedupe_key = models.CharField(max_length=200, unique=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"], name="notif_recipient_recent_idx"),
            models.Index(
                fields=["recipient"],
                condition=models.Q(is_read=False),
                name="notif_unread_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.type} -> {self.recipient_id}"


NOTIFICATION_TYPE_CHOICES = Notification.Type.choices

# Delivery policy: every type is stored and pushed over WebSocket; these are also emailed.
EMAIL_TYPES = {
    Notification.Type.INSPECTION_CONFIRMED,
    Notification.Type.INSPECTION_CANCELLED,
    Notification.Type.PAYMENT_REMINDER,
    Notification.Type.PAYMENT_OVERDUE,
    Notification.Type.AGENT_VERIFICATION,
}
