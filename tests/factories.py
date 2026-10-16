import datetime

import factory
from django.utils import timezone as django_timezone

from apps.accounts.models import User
from apps.agents.models import AgentProfile

DEFAULT_PASSWORD = "Correct-Horse-9"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    name = factory.Sequence(lambda n: f"User {n}")
    role = User.Role.TENANT
    # Verified by default, like every pre-existing account; pass email_verified_at=None
    # for a freshly registered one.
    email_verified_at = factory.LazyFunction(django_timezone.now)
    password = factory.PostGenerationMethodCall("set_password", DEFAULT_PASSWORD)

    @factory.post_generation
    def _save(obj, create, extracted, **kwargs):
        if create:
            obj.save()


class AgentFactory(UserFactory):
    role = User.Role.AGENT
    profile = factory.RelatedFactory(
        "tests.factories.AgentProfileFactory", factory_related_name="user"
    )


class AgentProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AgentProfile

    user = factory.SubFactory(UserFactory, role=User.Role.AGENT)
    agency = "Lagos Homes Ltd"
    trust_score = 60


class LandlordFactory(UserFactory):
    role = User.Role.LANDLORD


class PropertyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "properties.Property"

    landlord = factory.SubFactory(LandlordFactory)
    title = factory.Sequence(lambda n: f"Property {n}")
    address = factory.Sequence(lambda n: f"{n} Admiralty Way")
    city = "Lagos"
    state = "Lagos"
    neighborhood = "Lekki"
    photos = factory.LazyFunction(lambda: ["https://images.example.com/a.jpg"])
    bedrooms = 3
    bathrooms = 2
    sqft = 1500
    price_annual = 5_000_000
    status = "listed"
    occupancy_rate = 0


class AssignmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "properties.PropertyAgentAssignment"

    property = factory.SubFactory(PropertyFactory)
    agent = factory.SubFactory(AgentFactory)
    active = True


class TenancyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "tenancies.Tenancy"

    tenant = factory.SubFactory(UserFactory, role=User.Role.TENANT)
    property = factory.SubFactory(PropertyFactory)
    unit = factory.Sequence(lambda n: f"Flat {n}")
    lease_start = factory.LazyFunction(lambda: datetime.date(2025, 10, 1))
    next_due_date = factory.LazyFunction(lambda: datetime.date(2026, 10, 1))


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "payments.PaymentEntry"

    tenancy = factory.SubFactory(TenancyFactory)
    amount = 5_000_000
    due_date = factory.LazyFunction(lambda: datetime.date(2025, 10, 1))
    paid_date = factory.LazyFunction(lambda: datetime.date(2025, 9, 28))
    method = "bank_transfer"
    status = "paid"
    logged_by = factory.SubFactory(AgentFactory)


class MaintenanceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "maintenance.MaintenanceRequest"

    property = factory.SubFactory(PropertyFactory)
    tenant = factory.SubFactory(UserFactory, role=User.Role.TENANT)
    issue_type = "Plumbing"
    description = "Kitchen sink is leaking."
    priority = "medium"


class InspectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "inspections.Inspection"

    property = factory.SubFactory(PropertyFactory)
    tenant = factory.SubFactory(UserFactory, role=User.Role.TENANT)
    agent = factory.SubFactory(AgentFactory)
    prospect_name = "Chidi Okafor"
    scheduled_at = factory.LazyFunction(lambda: django_timezone.now() + datetime.timedelta(days=3))


class ThreadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "messaging.MessageThread"
        skip_postgeneration_save = True

    @factory.post_generation
    def members(obj, create, extracted, **kwargs):
        if create and extracted:
            from apps.messaging.models import ThreadParticipant

            for user in extracted:
                ThreadParticipant.objects.create(thread=obj, user=user)
