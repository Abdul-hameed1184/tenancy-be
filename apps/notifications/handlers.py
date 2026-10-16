"""
Domain event -> notification mapping.

Handlers run after the causing transaction commits (via the outbox), possibly more than
once. Every notification's dedupe_key derives from the event id, which makes reruns
harmless.
"""

from apps.agents.events import AgentVerificationRejected, AgentVerified
from apps.common.events import subscribe
from apps.inspections.events import (
    InspectionCancelled,
    InspectionCompleted,
    InspectionConfirmed,
    InspectionRequested,
)
from apps.maintenance.events import MaintenanceCreated, MaintenanceStatusChanged
from apps.messaging.events import MessageSent
from apps.payments.events import PaymentPaid
from apps.properties.events import AgentAssigned, AgentUnassigned
from apps.properties.selectors import active_assignments

from .models import Notification
from .services import notify

T = Notification.Type


def _key(event, recipient_id) -> str:
    return f"{event.name}:{event.event_id}:{recipient_id}"


@subscribe(MessageSent)
def on_message_sent(event: MessageSent) -> None:
    from apps.messaging.models import Message

    message = Message.objects.select_related("sender").filter(pk=event.message_id).first()
    if message is None:
        return
    preview = message.body if len(message.body) <= 120 else message.body[:117] + "..."
    for recipient_id in event.recipient_ids:
        notify(
            recipient_id=recipient_id,
            type=T.NEW_MESSAGE,
            title=f"New message from {message.sender.name}",
            message=preview,
            data={"threadId": event.thread_id, "messageId": event.message_id},
            dedupe_key=_key(event, recipient_id),
        )


@subscribe(MaintenanceCreated)
def on_maintenance_created(event: MaintenanceCreated) -> None:
    assignment = active_assignments().filter(property_id=event.property_id).first()
    if assignment is None:
        return
    notify(
        recipient_id=assignment.agent_id,
        type=T.MAINTENANCE_REPORTED,
        title="New maintenance request",
        message=f"A tenant reported a {event.priority}-priority issue.",
        data={"maintenanceRequestId": event.request_id, "propertyId": event.property_id},
        dedupe_key=_key(event, assignment.agent_id),
    )


@subscribe(MaintenanceStatusChanged)
def on_maintenance_status_changed(event: MaintenanceStatusChanged) -> None:
    notify(
        recipient_id=event.tenant_id,
        type=T.MAINTENANCE_UPDATE,
        title="Maintenance update",
        message=f"Your {event.issue_type} request is now {event.to_status.replace('_', ' ')}.",
        data={"maintenanceRequestId": event.request_id, "status": event.to_status},
        dedupe_key=_key(event, event.tenant_id),
    )


@subscribe(InspectionRequested)
def on_inspection_requested(event: InspectionRequested) -> None:
    notify(
        recipient_id=event.agent_id,
        type=T.INSPECTION_REQUESTED,
        title="New inspection request",
        message="A tenant requested a viewing. Please confirm it.",
        data={"inspectionId": event.inspection_id, "scheduledAt": event.scheduled_at},
        dedupe_key=_key(event, event.agent_id),
    )


@subscribe(InspectionConfirmed)
def on_inspection_confirmed(event: InspectionConfirmed) -> None:
    notify(
        recipient_id=event.tenant_id,
        type=T.INSPECTION_CONFIRMED,
        title="Inspection confirmed",
        message="Your viewing has been confirmed by the agent.",
        data={"inspectionId": event.inspection_id, "scheduledAt": event.scheduled_at},
        dedupe_key=_key(event, event.tenant_id),
    )


@subscribe(InspectionCompleted)
def on_inspection_completed(event: InspectionCompleted) -> None:
    notify(
        recipient_id=event.tenant_id,
        type=T.INSPECTION_COMPLETED,
        title="Inspection completed",
        message="Your viewing has been marked as completed.",
        data={"inspectionId": event.inspection_id},
        dedupe_key=_key(event, event.tenant_id),
    )


@subscribe(InspectionCancelled)
def on_inspection_cancelled(event: InspectionCancelled) -> None:
    # Tell the other party: whoever cancelled already knows.
    recipient = event.agent_id if event.actor_id == event.tenant_id else event.tenant_id
    notify(
        recipient_id=recipient,
        type=T.INSPECTION_CANCELLED,
        title="Inspection cancelled",
        message="A scheduled viewing was cancelled.",
        data={"inspectionId": event.inspection_id, "scheduledAt": event.scheduled_at},
        dedupe_key=_key(event, recipient),
    )


@subscribe(PaymentPaid)
def on_payment_paid(event: PaymentPaid) -> None:
    notify(
        recipient_id=event.tenant_id,
        type=T.PAYMENT_RECEIVED,
        title="Payment received",
        message=f"Your rent payment of NGN {event.amount:,} has been recorded.",
        data={"tenancyId": event.tenancy_id, "nextDueDate": event.next_due_date},
        dedupe_key=_key(event, event.tenant_id),
    )


@subscribe(AgentVerified)
def on_agent_verified(event: AgentVerified) -> None:
    notify(
        recipient_id=event.agent_id,
        type=T.AGENT_VERIFICATION,
        title="You're verified",
        message=f"Your agent profile is verified. Trust score: {event.trust_score}.",
        data={"verificationStatus": "verified", "trustScore": event.trust_score},
        dedupe_key=_key(event, event.agent_id),
    )


@subscribe(AgentVerificationRejected)
def on_agent_rejected(event: AgentVerificationRejected) -> None:
    notify(
        recipient_id=event.agent_id,
        type=T.AGENT_VERIFICATION,
        title="Verification not approved",
        message="Your verification was not approved. Please review your documents.",
        data={"verificationStatus": "rejected"},
        dedupe_key=_key(event, event.agent_id),
    )


@subscribe(AgentAssigned)
def on_agent_assigned(event: AgentAssigned) -> None:
    notify(
        recipient_id=event.agent_id,
        type=T.PROPERTY_ASSIGNMENT,
        title="New property assigned",
        message="A landlord assigned you to manage a property.",
        data={"propertyId": event.property_id, "active": True},
        dedupe_key=_key(event, event.agent_id),
    )
    if event.previous_agent_id:
        notify(
            recipient_id=event.previous_agent_id,
            type=T.PROPERTY_ASSIGNMENT,
            title="Property reassigned",
            message="You no longer manage a property; it was assigned to another agent.",
            data={"propertyId": event.property_id, "active": False},
            dedupe_key=_key(event, event.previous_agent_id),
        )


@subscribe(AgentUnassigned)
def on_agent_unassigned(event: AgentUnassigned) -> None:
    notify(
        recipient_id=event.agent_id,
        type=T.PROPERTY_ASSIGNMENT,
        title="Property unassigned",
        message="You no longer manage a property.",
        data={"propertyId": event.property_id, "active": False},
        dedupe_key=_key(event, event.agent_id),
    )
