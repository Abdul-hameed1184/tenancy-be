from django.contrib import admin

from .models import Tenancy


@admin.register(Tenancy)
class TenancyAdmin(admin.ModelAdmin):
    """The contract has no create-tenancy endpoint; operations staff create them here."""

    list_display = ["tenant", "property", "unit", "lease_start", "next_due_date", "ended_at"]
    list_filter = ["ended_at"]
    search_fields = ["tenant__email", "tenant__name", "property__title", "unit"]
    list_select_related = ["tenant", "property"]
    raw_id_fields = ["tenant", "property"]
