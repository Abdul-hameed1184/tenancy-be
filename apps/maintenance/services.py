from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import Action, record
from apps.common.events import publish
from apps.common.exceptions import Conflict
from apps.common.transitions import transition
from apps.tenancies.models import Tenancy

from .events import MaintenanceCreated, MaintenanceStatusChanged
from .models import PREDECESSOR, MaintenanceRequest


class NotYourProperty(Exception):
    pass


def create_request(*, tenant: User, data: dict, request=None) -> MaintenanceRequest:
    # A tenant may only report issues for the property they currently rent.
    rents_it = Tenancy.objects.filter(
        tenant=tenant, property_id=data["propertyId"], ended_at__isnull=True
    ).exists()
    if not rents_it:
        raise NotYourProperty
    with transaction.atomic():
        req = MaintenanceRequest.objects.create(
            property_id=data["propertyId"],
            tenant=tenant,
            issue_type=data["issueType"],
            description=data["description"],
            priority=data["priority"],
        )
        publish(
            MaintenanceCreated(
                request_id=str(req.pk),
                property_id=str(req.property_id),
                tenant_id=str(tenant.pk),
                priority=req.priority,
            )
        )
        record(Action.MAINTENANCE_CREATED, actor=tenant, entity=req, request=request)
    return req


def change_status(*, req: MaintenanceRequest, to: str, actor: User, request=None):
    predecessor = PREDECESSOR.get(to)
    if predecessor is None:
        raise Conflict(f"A request can't be moved back to {to.replace('_', ' ')}.")
    now = timezone.now()
    extra = {"updated_at": now}
    if to == MaintenanceRequest.Status.COMPLETED:
        extra["completed_at"] = now
    with transaction.atomic():
        updated = transition(
            MaintenanceRequest.objects.all(),
            req.pk,
            allowed_from=[predecessor],
            to=to,
            noun="maintenance request",
            **extra,
        )
        publish(
            MaintenanceStatusChanged(
                request_id=str(updated.pk),
                property_id=str(updated.property_id),
                tenant_id=str(updated.tenant_id),
                issue_type=updated.issue_type,
                from_status=predecessor,
                to_status=to,
                changed_by_id=str(actor.pk),
            )
        )
        record(
            Action.MAINTENANCE_STATUS_CHANGED,
            actor=actor,
            entity=updated,
            metadata={"from": predecessor, "to": to},
            request=request,
        )
    return updated
