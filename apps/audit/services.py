from typing import Any

from django.db import models

from apps.common.request import client_ip, user_agent

from .models import AuditLog

# Keys whose values must never be persisted, whatever a caller passes in.
_SENSITIVE_KEY_FRAGMENTS = ("password", "token", "secret", "authorization", "ticket", "cookie")


class Action:
    USER_REGISTERED = "USER_REGISTERED"
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    TOKEN_REUSE_DETECTED = "TOKEN_REUSE_DETECTED"
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    PASSWORD_RESET = "PASSWORD_RESET"
    PROFILE_UPDATED = "PROFILE_UPDATED"
    EMAIL_VERIFIED = "EMAIL_VERIFIED"
    PROPERTY_CREATED = "PROPERTY_CREATED"
    PROPERTY_UPDATED = "PROPERTY_UPDATED"
    AGENT_ASSIGNED = "AGENT_ASSIGNED"
    AGENT_UNASSIGNED = "AGENT_UNASSIGNED"
    TENANT_ASSIGNMENT_REQUESTED = "TENANT_ASSIGNMENT_REQUESTED"
    TENANT_ASSIGNMENT_APPROVED = "TENANT_ASSIGNMENT_APPROVED"
    TENANT_ASSIGNMENT_REJECTED = "TENANT_ASSIGNMENT_REJECTED"
    PAYMENT_CREATED = "PAYMENT_CREATED"
    PAYMENT_MARKED_PAID = "PAYMENT_MARKED_PAID"
    MAINTENANCE_CREATED = "MAINTENANCE_CREATED"
    MAINTENANCE_STATUS_CHANGED = "MAINTENANCE_STATUS_CHANGED"
    INSPECTION_REQUESTED = "INSPECTION_REQUESTED"
    INSPECTION_CONFIRMED = "INSPECTION_CONFIRMED"
    INSPECTION_COMPLETED = "INSPECTION_COMPLETED"
    INSPECTION_CANCELLED = "INSPECTION_CANCELLED"
    AGENT_VERIFIED = "AGENT_VERIFIED"
    AGENT_VERIFICATION_REJECTED = "AGENT_VERIFICATION_REJECTED"
    REPORT_CREATED = "REPORT_CREATED"
    REPORT_RESOLVED = "REPORT_RESOLVED"


def record(
    action: str,
    *,
    actor=None,
    entity: models.Model | None = None,
    entity_type: str = "",
    entity_id: str = "",
    metadata: dict[str, Any] | None = None,
    request=None,
) -> AuditLog:
    if entity is not None:
        entity_type = entity_type or entity._meta.label_lower
        entity_id = entity_id or str(entity.pk)
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=_scrub(metadata or {}),
        ip_address=client_ip(request) if request is not None else None,
        user_agent=user_agent(request) if request is not None else "",
    )


def _scrub(data: dict[str, Any]) -> dict[str, Any]:
    clean = {}
    for key, value in data.items():
        if any(fragment in key.lower() for fragment in _SENSITIVE_KEY_FRAGMENTS):
            continue
        clean[key] = _scrub(value) if isinstance(value, dict) else value
    return clean
