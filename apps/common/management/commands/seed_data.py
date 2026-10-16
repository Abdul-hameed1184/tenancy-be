"""
python manage.py seed_data [--force]

Deterministic demo data: one account per role (plus a few extras), properties across three
cities, agent assignments, tenancies, a payment ledger, maintenance requests, inspections,
message threads, reports and notifications.

- Ids are uuid5(name), so re-running is idempotent and demo links survive reseeds.
- The shared password comes from SEED_PASSWORD (default below is demo-only, never real).
- Refuses to run with DEBUG=False unless --force, so it can't silently pollute production.
- Writes go straight through the ORM, not the services: seeding shouldn't fire
  notifications, emails or audit entries for events that never happened.
"""

import datetime
import os
import uuid
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.agents.models import AgentProfile
from apps.inspections.models import Inspection
from apps.maintenance.models import MaintenanceRequest
from apps.messaging.models import Message, MessageThread, ThreadParticipant
from apps.notifications.models import Notification
from apps.payments.models import PaymentEntry
from apps.properties.models import Property, PropertyAgentAssignment
from apps.reports.models import Report
from apps.tenancies.models import Tenancy

NAMESPACE = uuid.UUID("6f1d3b8e-6b5e-4c0a-9a57-9c1f0e2a7d10")
DEFAULT_PASSWORD = "PleetDemo!2026"  # noqa: S105 (documented demo-only; set SEED_PASSWORD)
PHOTO = "https://images.unsplash.com/photo-{}?auto=format&fit=crop&w=1200&q=80"


def sid(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


USERS = [
    # key, email, name, role
    ("admin", "admin@pleet.test", "Ada Admin", "admin"),
    ("landlord", "landlord@pleet.test", "Lanre Landlord", "landlord"),
    ("landlord2", "landlord2@pleet.test", "Ngozi Eze", "landlord"),
    ("agent", "agent@pleet.test", "Amaka Agent", "agent"),
    ("agent2", "agent2@pleet.test", "Tunde Bakare", "agent"),
    ("agent3", "agent3@pleet.test", "Bisi Adeyemi", "agent"),
    ("tenant", "tenant@pleet.test", "Tobi Tenant", "tenant"),
    ("tenant2", "tenant2@pleet.test", "Chidi Okafor", "tenant"),
]
AGENTS = {
    # key: (agency, status, trust)
    "agent": ("Lagos Prime Realty", "verified", 92),
    "agent2": ("Abuja Homes Co.", "pending", 55),
    "agent3": ("Garden City Lets", "unverified", 30),
}
PROPERTIES = [
    # key, landlord, title, city, state, hood, beds, baths, sqft, price, status, occ, feat, photo
    ("lekki-duplex", "landlord", "Ocean View Duplex", "Lagos", "Lagos", "Lekki Phase 1",
     4, 4, 3200, 12_000_000, "occupied", 100, True, "1600596542815-ffad4c1539a9"),
    ("ikoyi-flat", "landlord", "Ikoyi Executive Flat", "Lagos", "Lagos", "Ikoyi",
     3, 3, 2100, 9_500_000, "occupied", 100, True, "1502672260266-1c1ef2d93688"),
    ("yaba-studio", "landlord", "Yaba Smart Studio", "Lagos", "Lagos", "Yaba",
     1, 1, 650, 2_400_000, "listed", 0, False, "1522708323590-d24dbb6b0267"),
    ("maitama-villa", "landlord", "Maitama Garden Villa", "Abuja", "FCT", "Maitama",
     5, 5, 4500, 18_000_000, "listed", 40, True, "1613490493576-7fde63acd811"),
    ("gra-terrace", "landlord2", "GRA Terrace Home", "Port Harcourt", "Rivers", "GRA Phase 2",
     3, 2, 1800, 4_800_000, "unavailable", 0, False, "1568605114967-8130f3a36994"),
    ("wuse-apartment", "landlord2", "Wuse II Apartment", "Abuja", "FCT", "Wuse II",
     2, 2, 1200, 6_000_000, "listed", 0, False, "1493809842364-78817add7ffb"),
]  # fmt: skip
ASSIGNMENTS = [("lekki-duplex", "agent"), ("ikoyi-flat", "agent"), ("maitama-villa", "agent"),
               ("gra-terrace", "agent2"), ("wuse-apartment", "agent2")]  # fmt: skip


class Command(BaseCommand):
    help = "Seed deterministic demo data (one account per role, plus related records)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Allow when DEBUG=False.")

    def handle(self, *args, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to seed with DEBUG=False. Pass --force if intended.")
        password = os.environ.get("SEED_PASSWORD", DEFAULT_PASSWORD)
        with transaction.atomic():
            counts = self._seed(password)
        for label, n in counts.items():
            self.stdout.write(f"  {label:<16} {n}")
        self.stdout.write(
            self.style.SUCCESS(f"Seeded. Every demo account uses password: {password}")
        )
        for _, email, _, role in USERS:
            self.stdout.write(f"  {role:<9} {email}")

    def _seed(self, password: str) -> dict:
        tz = ZoneInfo(settings.PLEET_BUSINESS_TIME_ZONE)
        now = timezone.now()
        today = now.astimezone(tz).date()
        users = {}
        for key, email, name, role in USERS:
            user, created = User.objects.update_or_create(
                id=sid(f"user:{key}"),
                defaults={"email": email, "name": name, "role": role, "is_active": True,
                          "phone": "+2348000000" + str(len(users)).zfill(3),
                          "is_staff": role == "admin", "is_superuser": role == "admin",
                          "email_verified_at": now},  # demo accounts are pre-verified
            )  # fmt: skip
            if created or not user.check_password(password):
                user.set_password(password)
                user.save(update_fields=["password"])
            users[key] = user
        for key, (agency, status, trust) in AGENTS.items():
            AgentProfile.objects.update_or_create(
                user=users[key],
                defaults={"agency": agency, "verification_status": status, "trust_score": trust},
            )

        props = {}
        for (
            key,
            ll,
            title,
            city,
            state,
            hood,
            beds,
            baths,
            sqft,
            price,
            status,
            occ,
            feat,
            photo,
        ) in PROPERTIES:
            props[key], _ = Property.objects.update_or_create(
                id=sid(f"property:{key}"),
                defaults={"landlord": users[ll], "title": title, "address": f"{hood}, {city}",
                          "city": city, "state": state, "neighborhood": hood, "bedrooms": beds,
                          "bathrooms": baths, "sqft": sqft, "price_annual": price,
                          "status": status, "occupancy_rate": occ, "featured": feat,
                          "photos": [PHOTO.format(photo)]},
            )  # fmt: skip
        for prop_key, agent_key in ASSIGNMENTS:
            PropertyAgentAssignment.objects.get_or_create(
                id=sid(f"assignment:{prop_key}"),
                defaults={"property": props[prop_key], "agent": users[agent_key],
                          "assigned_by": props[prop_key].landlord,
                          "assigned_at": now - datetime.timedelta(days=40)},
            )  # fmt: skip

        tenancies = {
            "tenant": self._tenancy(sid("tenancy:tenant"), users["tenant"], props["lekki-duplex"],
                                    "Unit A", today - datetime.timedelta(days=360),
                                    today + datetime.timedelta(days=5)),
            "tenant2": self._tenancy(sid("tenancy:tenant2"), users["tenant2"], props["ikoyi-flat"],
                                     "Flat 3B", today - datetime.timedelta(days=420),
                                     today - datetime.timedelta(days=10)),
        }  # fmt: skip
        ledger = [
            ("p1", "tenant", 365 * 2, 12_000_000, "paid"),
            ("p2", "tenant", 365, 12_000_000, "paid"),
            ("p3", "tenant2", 420, 9_500_000, "paid"),
            ("p4", "tenant2", 10, 9_500_000, "overdue"),
        ]
        for key, who, days_ago, amount, status in ledger:
            due = today - datetime.timedelta(days=days_ago)
            if not PaymentEntry.objects.filter(id=sid(f"payment:{key}")).exists():  # append-only
                PaymentEntry.objects.create(
                    id=sid(f"payment:{key}"), tenancy=tenancies[who], amount=amount, due_date=due,
                    paid_date=due - datetime.timedelta(days=2) if status == "paid" else None,
                    method="bank_transfer", status=status, logged_by=users["agent"],
                    note="Seeded ledger entry",
                )  # fmt: skip

        MaintenanceRequest.objects.update_or_create(
            id=sid("maintenance:leak"),
            defaults={"property": props["lekki-duplex"], "tenant": users["tenant"],
                      "issue_type": "Plumbing", "priority": "high", "status": "reported",
                      "description": "Water is leaking under the kitchen sink."},
        )  # fmt: skip
        MaintenanceRequest.objects.update_or_create(
            id=sid("maintenance:ac"),
            defaults={"property": props["ikoyi-flat"], "tenant": users["tenant2"],
                      "issue_type": "Air conditioning", "priority": "medium",
                      "status": "in_progress", "description": "Bedroom AC is not cooling."},
        )  # fmt: skip

        for key, days, status in [("viewing-1", 2, "requested"), ("viewing-2", 0, "confirmed")]:
            slot = datetime.datetime.combine(today + datetime.timedelta(days=days),
                                             datetime.time(15), tzinfo=tz)  # fmt: skip
            Inspection.objects.update_or_create(
                id=sid(f"inspection:{key}"),
                defaults={"property": props["maitama-villa"], "tenant": users["tenant"],
                          "agent": users["agent"], "prospect_name": users["tenant"].name,
                          "scheduled_at": slot, "status": status,
                          "confirmed_at": now if status == "confirmed" else None},
            )  # fmt: skip

        thread, _ = MessageThread.objects.update_or_create(
            id=sid("thread:tenant-agent"),
            defaults={"property": props["lekki-duplex"], "last_message_at": now},
        )
        for user in (users["tenant"], users["agent"]):
            ThreadParticipant.objects.get_or_create(thread=thread, user=user)
        for i, (sender, body) in enumerate([
            ("tenant", "Hello! The kitchen sink is leaking again."),
            ("agent", "Thanks for reporting it. A plumber is booked for tomorrow at 10am."),
            ("tenant", "Perfect, I'll be home. Thank you!"),
        ]):  # fmt: skip
            Message.objects.update_or_create(
                id=sid(f"message:{i}"),
                defaults={"thread": thread, "sender": users[sender], "body": body,
                          "sent_at": now - datetime.timedelta(minutes=30 - i * 10)},
            )  # fmt: skip

        Report.objects.update_or_create(
            id=sid("report:listing"),
            defaults={"type": "listing", "target_property": props["gra-terrace"],
                      "reason": "Photos don't match the actual property.",
                      "reported_by": users["landlord"]},
        )  # fmt: skip
        Notification.objects.update_or_create(
            dedupe_key="seed:welcome-tenant",
            defaults={"recipient": users["tenant"], "type": "payment_reminder",
                      "title": "Rent due soon",
                      "message": "Your rent for Ocean View Duplex is due in 5 days."},
        )  # fmt: skip

        return {
            "users": User.objects.filter(id__in=[u.id for u in users.values()]).count(),
            "properties": len(props),
            "assignments": len(ASSIGNMENTS),
            "tenancies": len(tenancies),
            "payments": len(ledger),
            "maintenance": 2,
            "inspections": 2,
            "messages": 3,
        }

    @staticmethod
    def _tenancy(pk, tenant, prop, unit, lease_start, next_due):
        tenancy, _ = Tenancy.objects.update_or_create(
            id=pk,
            defaults={"tenant": tenant, "property": prop, "unit": unit,
                      "lease_start": lease_start, "next_due_date": next_due},
        )  # fmt: skip
        return tenancy
