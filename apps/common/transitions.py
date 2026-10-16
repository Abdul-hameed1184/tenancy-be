"""
Race-free state transitions with a conditional UPDATE.

    UPDATE inspection SET status = 'confirmed', confirmed_at = now()
    WHERE id = %s AND status IN ('requested')

PostgreSQL evaluates the WHERE clause and applies the write atomically for that row. Two
concurrent "confirm" clicks can't both succeed: one updates one row, the other updates
zero rows and gets a 409. No SELECT ... FOR UPDATE round trip is needed because nothing
else has to be read under the lock. The current status *is* the precondition.
"""

from collections.abc import Iterable

from django.db import models

from .exceptions import Conflict


def transition(
    queryset: models.QuerySet,
    pk,
    *,
    allowed_from: Iterable[str],
    to: str,
    noun: str,
    **extra_fields,
):
    """Move one row from any of `allowed_from` to `to`; returns the refreshed instance."""
    allowed = list(allowed_from)
    updated = queryset.filter(pk=pk, status__in=allowed).update(status=to, **extra_fields)
    instance = queryset.get(pk=pk)
    if updated == 0:
        raise Conflict(
            f"This {noun} is {instance.status.replace('_', ' ')} and can't be moved to "
            f"{to.replace('_', ' ')}."
        )
    return instance
