from django.contrib import admin

from .models import PaymentEntry


@admin.register(PaymentEntry)
class PaymentEntryAdmin(admin.ModelAdmin):
    """Read-only: the ledger is append-only, even for staff."""

    list_display = ["tenancy", "amount", "due_date", "status", "method", "logged_by", "logged_at"]
    list_filter = ["status", "method"]
    list_select_related = ["tenancy", "logged_by"]
    search_fields = ["tenancy__tenant__email", "tenancy__property__title"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
