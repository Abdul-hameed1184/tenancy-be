from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import Action, record
from apps.common.events import publish
from apps.common.transitions import transition
from apps.properties.models import Property

from .events import ReportResolved
from .models import Report


class InvalidTarget(Exception):
    """Message is safe to show to the client."""


def file_report(*, reporter: User, type: str, target_id, reason: str, request=None) -> Report:
    fields = {"type": type, "reason": reason.strip(), "reported_by": reporter}
    if type == Report.Type.LISTING:
        target = Property.objects.filter(pk=target_id).first()
        if target is None:
            raise InvalidTarget("No listing with this id.")
        fields["target_property"] = target
    else:
        target = User.objects.filter(pk=target_id, is_active=True).first()
        if target is None:
            raise InvalidTarget("No user with this id.")
        if target.pk == reporter.pk:
            raise InvalidTarget("You can't report yourself.")
        fields["target_user"] = target
    with transaction.atomic():
        report = Report.objects.create(**fields)
        record(
            Action.REPORT_CREATED,
            actor=reporter,
            entity=report,
            metadata={"type": type, "target_id": str(target_id)},
            request=request,
        )
    return report


def resolve(*, report: Report, admin: User, request=None) -> Report:
    with transaction.atomic():
        resolved = transition(
            Report.objects.all(),
            report.pk,
            allowed_from=[Report.Status.OPEN],
            to=Report.Status.RESOLVED,
            noun="report",
            resolved_at=timezone.now(),
            resolved_by_id=admin.pk,
        )
        publish(
            ReportResolved(
                report_id=str(resolved.pk),
                reported_by_id=str(resolved.reported_by_id),
                resolved_by_id=str(admin.pk),
            )
        )
        record(Action.REPORT_RESOLVED, actor=admin, entity=resolved, request=request)
    return resolved
