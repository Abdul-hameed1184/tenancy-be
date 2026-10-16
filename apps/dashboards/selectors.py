"""
Dashboard statistics, computed entirely in PostgreSQL with conditional aggregates
(COUNT(*) FILTER (WHERE ...), SUM(...) FILTER (...)): one pass per table, no rows loaded
into Python, constant query count regardless of portfolio size.

"Today" and "this month" are calendar boundaries in the business timezone (Africa/Lagos),
converted to UTC instants for datetime comparisons.
"""

import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.db.models.functions import Coalesce, Lower

from apps.inspections.models import Inspection
from apps.maintenance.models import MaintenanceRequest
from apps.payments.models import PaymentEntry
from apps.properties.models import Property
from apps.properties.selectors import active_assignments
from apps.tenancies.models import Tenancy

HIGH_PRIORITY_DUE_WINDOW_DAYS = 7


def _clock():
    tz = ZoneInfo(settings.PLEET_BUSINESS_TIME_ZONE)
    now = datetime.datetime.now(tz)
    today = now.date()
    day_start = datetime.datetime.combine(today, datetime.time.min, tzinfo=tz)
    month_start = day_start.replace(day=1)
    return today, day_start, day_start + datetime.timedelta(days=1), month_start


def agent_stats(agent) -> dict:
    today, day_start, day_end, month_start = _clock()
    managed = active_assignments().filter(agent=agent)
    managed_property_ids = managed.values("property_id")

    # activeProperties: active assignments to this agent.
    # activePropertiesNewThisMonth: of those, assigned since the 1st of this month.
    assignments = managed.aggregate(
        active=Count("pk"),
        new_this_month=Count("pk", filter=Q(assigned_at__gte=month_start)),
    )
    # totalTenants: current tenancies on those properties.
    # totalTenantsHighPriority: of those, overdue or due within 7 days.
    tenancies = Tenancy.objects.filter(
        ended_at__isnull=True, property_id__in=managed_property_ids
    ).aggregate(
        total=Count("pk"),
        high=Count(
            "pk",
            filter=Q(
                next_due_date__lte=today + datetime.timedelta(days=HIGH_PRIORITY_DUE_WINDOW_DAYS)
            ),
        ),
    )
    # maintenancePending: requests on those properties not yet completed.
    # maintenanceHighPriority: of those, priority = high.
    maintenance = (
        MaintenanceRequest.objects.filter(property_id__in=managed_property_ids)
        .exclude(status=MaintenanceRequest.Status.COMPLETED)
        .aggregate(
            pending=Count("pk"),
            high=Count("pk", filter=Q(priority=MaintenanceRequest.Priority.HIGH)),
        )
    )
    # upcomingInspections: this agent's inspections that are requested or confirmed.
    # inspectionsScheduledToday: of those, scheduled today (Lagos calendar day).
    inspections = Inspection.objects.filter(
        agent=agent,
        status__in=[Inspection.Status.REQUESTED, Inspection.Status.CONFIRMED],
    ).aggregate(
        upcoming=Count("pk"),
        today=Count("pk", filter=Q(scheduled_at__gte=day_start, scheduled_at__lt=day_end)),
    )
    return {
        "activeProperties": assignments["active"],
        "activePropertiesNewThisMonth": assignments["new_this_month"],
        "totalTenants": tenancies["total"],
        "totalTenantsHighPriority": tenancies["high"],
        "maintenancePending": maintenance["pending"],
        "maintenanceHighPriority": maintenance["high"],
        "upcomingInspections": inspections["upcoming"],
        "inspectionsScheduledToday": inspections["today"],
    }


def landlord_stats(landlord) -> dict:
    today, _, _, month_start = _clock()
    properties = Property.objects.filter(landlord=landlord).annotate(
        has_current_tenant=Exists(
            Tenancy.objects.filter(property_id=OuterRef("pk"), ended_at__isnull=True)
        )
    )
    portfolio = properties.aggregate(
        rent_total=Coalesce(Sum("price_annual"), 0),
        rent_baseline=Coalesce(Sum("price_annual", filter=Q(created_at__lt=month_start)), 0),
        count=Count("pk"),
        occupied=Count("pk", filter=Q(has_current_tenant=True)),
        vacant=Count("pk", filter=Q(has_current_tenant=False)),
        cities=Count(Lower("city"), distinct=True),
    )
    ledger = PaymentEntry.objects.filter(
        tenancy__property__landlord=landlord, due_date__year=today.year
    ).aggregate(
        annual_revenue=Coalesce(
            Sum("amount", filter=Q(status=PaymentEntry.Status.PAID, paid_date__year=today.year)), 0
        ),
        paid=Coalesce(Sum("amount", filter=Q(status=PaymentEntry.Status.PAID)), 0),
        unpaid=Coalesce(
            Sum("amount", filter=Q(status__in=[PaymentEntry.Status.DUE, PaymentEntry.Status.OVERDUE])),
            0,
        ),
    )

    # Report rent roll rather than imply an unsupported market valuation.
    value_now = portfolio["rent_total"]
    # rentRollChangePct: value now vs. the portfolio as it stood at the start of this
    # month (properties created before then). 0 when there is no baseline yet.
    value_before = portfolio["rent_baseline"]
    change_pct = round((value_now - value_before) / value_before * 100, 1) if value_before else 0
    billed = ledger["paid"] + ledger["unpaid"]
    collection = round(ledger["paid"] / billed * 100) if billed else 100
    tenancy_count = Tenancy.objects.filter(
        property__landlord=landlord, ended_at__isnull=True
    ).count()
    property_count = portfolio["count"]

    return {
        "totalPortfolioValue": value_now,
        "portfolioValueChangePct": change_pct,
        "annualRevenue": ledger["annual_revenue"],
        "collectionRatePct": collection,
        "occupancyRatePct": round(portfolio["occupied"] / property_count * 100) if property_count else 0,
        "vacantUnits": portfolio["vacant"],
        "occupiedUnits": tenancy_count,
        "occupiedProperties": portfolio["occupied"],
        "managedAssets": portfolio["count"],
        "citiesCount": portfolio["cities"],
    }
