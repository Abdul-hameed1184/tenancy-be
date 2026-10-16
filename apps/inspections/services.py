from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import Action, record
from apps.common.events import publish
from apps.common.transitions import transition
from apps.properties.models import Property
from apps.properties.selectors import active_assignments
from apps.tenancies.models import Tenancy

from .events import EVENT_FOR_ACTION, InspectionRequested
from .models import TRANSITIONS, Inspection

AUDIT_FOR_ACTION = {
    "confirm": Action.INSPECTION_CONFIRMED,
    "complete": Action.INSPECTION_COMPLETED,
    "cancel": Action.INSPECTION_CANCELLED,
}


class BookingError(Exception):
    """Message is safe to show to the client."""


def _event_kwargs(insp: Inspection, actor: User) -> dict:
    return {
        "inspection_id": str(insp.pk),
        "property_id": str(insp.property_id),
        "tenant_id": str(insp.tenant_id),
        "agent_id": str(insp.agent_id),
        "scheduled_at": insp.scheduled_at.isoformat(),
        "actor_id": str(actor.pk),
    }


def request_inspection(*, tenant: User, data: dict, request=None) -> Inspection:
    with transaction.atomic():
        prop = Property.objects.select_for_update().filter(pk=data["propertyId"]).first()
        if prop is None:
            raise BookingError("This property doesn't exist.")
        if prop.status != Property.Status.LISTED or Tenancy.objects.filter(
            property=prop, ended_at__isnull=True
        ).exists():
            raise BookingError("This property is occupied or unavailable for inspection.")

        assignment = active_assignments().filter(property=prop).first()
        if assignment is None:
            raise BookingError("This property has no managing agent and can't be booked.")
        claimed = data.get("agentId")
        if claimed and claimed != assignment.agent_id:
            # The page was stale: the property changed agents since it was loaded.
            raise BookingError("This property's agent has changed. Refresh and try again.")

        insp = Inspection.objects.create(
            property_id=data["propertyId"],
            tenant=tenant,
            agent_id=assignment.agent_id,
            prospect_name=data["prospectName"],
            scheduled_at=data["scheduledAt"],
        )
        publish(InspectionRequested(**_event_kwargs(insp, tenant)))
        record(Action.INSPECTION_REQUESTED, actor=tenant, entity=insp, request=request)
    return insp


def apply_transition(*, insp: Inspection, action: str, actor: User, request=None) -> Inspection:
    allowed_from, to = TRANSITIONS[action]
    now = timezone.now()
    extra = {
        "confirm": {"confirmed_at": now},
        "complete": {"completed_at": now},
        "cancel": {"cancelled_at": now, "cancelled_by_id": actor.pk},
    }[action]
    with transaction.atomic():
        updated = transition(
            Inspection.objects.all(),
            insp.pk,
            allowed_from=allowed_from,
            to=to,
            noun="inspection",
            **extra,
        )
        publish(EVENT_FOR_ACTION[action](**_event_kwargs(updated, actor)))
        record(AUDIT_FOR_ACTION[action], actor=actor, entity=updated, request=request)
    return updated
