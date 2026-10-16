from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel


class AppendOnlyError(Exception):
    pass


class AppendOnlyQuerySet(models.QuerySet):
    """Bulk UPDATE/DELETE are refused in Python too. The DB trigger is the final word."""

    def update(self, **kwargs):
        raise AppendOnlyError("The payment ledger is append-only.")

    def delete(self):
        raise AppendOnlyError("The payment ledger is append-only.")


class PaymentEntry(UUIDModel):
    """
    One immutable ledger line. Corrections are new entries, never edits, so the history of
    what was recorded, when and by whom can't be rewritten.
    """

    class Method(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        CARD = "card", "Card"
        CASH = "cash", "Cash"
        CHEQUE = "cheque", "Cheque"

    class Status(models.TextChoices):
        PAID = "paid", "Paid"
        DUE = "due", "Due"
        OVERDUE = "overdue", "Overdue"

    tenancy = models.ForeignKey(
        "tenancies.Tenancy", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.PositiveBigIntegerField()  # whole Naira
    due_date = models.DateField()
    paid_date = models.DateField(null=True, blank=True)
    method = models.CharField(max_length=16, choices=Method.choices)
    status = models.CharField(max_length=8, choices=Status.choices)
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="logged_payments"
    )
    logged_at = models.DateTimeField(default=timezone.now, editable=False)
    note = models.CharField(max_length=1000, blank=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["due_date", "logged_at"]
        verbose_name_plural = "payment entries"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="payments_amount_positive"
            ),
            models.CheckConstraint(
                condition=~models.Q(status="paid") | models.Q(paid_date__isnull=False),
                name="payments_paid_has_paid_date",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["paid", "due", "overdue"]),
                name="payments_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(method__in=["bank_transfer", "card", "cash", "cheque"]),
                name="payments_method_valid",
            ),
            # A period can be paid once. This is what makes a duplicate concurrent "paid"
            # request fail cleanly instead of double-counting revenue.
            models.UniqueConstraint(
                fields=["tenancy", "due_date"],
                condition=models.Q(status="paid"),
                name="payments_one_paid_per_period",
                violation_error_message="This due date has already been paid.",
            ),
        ]
        indexes = [
            models.Index(fields=["tenancy", "due_date"], name="payments_tenancy_due_idx"),
            models.Index(fields=["due_date", "status"], name="payments_due_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.amount} {self.status} due {self.due_date} ({self.tenancy_id})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Payment entries can't be modified once recorded.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Payment entries can't be deleted.")


PAYMENT_STATUS_CHOICES = PaymentEntry.Status.choices  # referenced by OpenAPI enum naming
