import threading

import pytest
from django.db import connection

from apps.properties import services
from apps.properties.models import PropertyAgentAssignment
from tests.factories import AgentFactory, PropertyFactory


@pytest.mark.django_db(transaction=True)
def test_concurrent_assignments_serialise_on_the_property_lock():
    """
    Two landlord tabs assign different agents to an unmanaged property simultaneously.

    There's no existing assignment row to lock, so without the property-row lock both
    transactions would insert an active row and one would crash on the unique index. With
    the lock the second waits, then cleanly replaces the first. Both requests succeed, and
    exactly one active assignment remains.
    """
    prop = PropertyFactory()
    agents = [AgentFactory(), AgentFactory()]
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(agent):
        try:
            barrier.wait()
            services.assign_agent(prop=prop, agent_id=agent.pk, actor=prop.landlord)
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(a,)) for a in agents]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    rows = PropertyAgentAssignment.objects.filter(property=prop)
    assert rows.count() == 2
    assert rows.filter(active=True).count() == 1
