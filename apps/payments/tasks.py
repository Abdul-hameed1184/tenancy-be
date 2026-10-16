"""
Scheduled rent jobs (Celery Beat, Africa/Lagos time):

    07:00 daily  send_rent_due_reminders  tenancies due within 7 days -> tenant + agent
    00:15 daily  flag_overdue_rent        tenancies past due -> tenant, agent, landlord

Both are idempotent and catch-up based. Each reminder's dedupe_key is
(kind, tenancy, due date, recipient), so re-running a job, running it late after Beat was
down, or running two Beats by mistake never sends a second reminder for the same due date.
Reminders are notifications; the append-only ledger is never modified.
"""

import datetime
from zoneinfo import ZoneInfo

from celery import shared_task
from django.conf import settings
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.properties.selectors import active_assignments
from apps.tenancies.models import Tenancy

REMINDER_WINDOW_DAYS = 7


def business_today() -> datetime.date:
    return timezone.now().astimezone(ZoneInfo(settings.PLEET_BUSINESS_TIME_ZONE)).date()


def _current_tenancies():
    agent = active_assignments().filter(property=OuterRef("property_id")).values("agent_id")[:1]
    return (
        Tenancy.objects.filter(ended_at__isnull=True)
        .select_related("property", "tenant")
        .annotate(agent_id=Subquery(agent))
    )


@shared_task
def send_rent_due_reminders() -> int:
    today = business_today()
    horizon = today + datetime.timedelta(days=REMINDER_WINDOW_DAYS)
    created = 0
    for tenancy in _current_tenancies().filter(next_due_date__range=(today, horizon)).iterator():
        due = tenancy.next_due_date.isoformat()
        days = (tenancy.next_due_date - today).days
        when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        recipients = [(tenancy.tenant_id, f"Your rent for {tenancy.property.title} is due {when}.")]
        if tenancy.agent_id:
            recipients.append(
                (
                    tenancy.agent_id,
                    f"Rent for {tenancy.property.title} ({tenancy.unit}) is due {when}.",
                )
            )
        for recipient_id, message in recipients:
            _, was_created = notify(
                recipient_id=recipient_id,
                type=Notification.Type.PAYMENT_REMINDER,
                title="Rent due soon",
                message=message,
                data={"tenancyId": str(tenancy.pk), "dueDate": due},
                dedupe_key=f"rent-due:{tenancy.pk}:{due}:{recipient_id}",
            )
            created += was_created
    return created


@shared_task
def flag_overdue_rent() -> int:
    today = business_today()
    created = 0
    for tenancy in _current_tenancies().filter(next_due_date__lt=today).iterator():
        due = tenancy.next_due_date.isoformat()
        recipients = {tenancy.tenant_id, tenancy.property.landlord_id}
        if tenancy.agent_id:
            recipients.add(tenancy.agent_id)
        for recipient_id in recipients:
            _, was_created = notify(
                recipient_id=recipient_id,
                type=Notification.Type.PAYMENT_OVERDUE,
                title="Rent overdue",
                message=f"Rent for {tenancy.property.title} ({tenancy.unit}) was due on {due}.",
                data={"tenancyId": str(tenancy.pk), "dueDate": due},
                dedupe_key=f"rent-overdue:{tenancy.pk}:{due}:{recipient_id}",
            )
            created += was_created
    return created
