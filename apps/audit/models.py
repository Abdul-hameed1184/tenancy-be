from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    """
    Who did what to which entity, and when.

    Rows are written in the same transaction as the change they describe, so an audit entry
    exists if and only if the change committed. Database-level append-only enforcement is
    added in the audit-hardening milestone.
    """

    # Bigint rather than UUID: audit rows are internal, high-volume and never exposed by id.
    id = models.BigAutoField(primary_key=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,  # keep the trail even if the user is deleted
        related_name="+",
    )
    action = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"], name="audit_entity_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_recent_idx"),
            models.Index(fields=["action", "-created_at"], name="audit_action_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type}:{self.entity_id} by {self.actor_id}"
