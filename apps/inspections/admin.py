from django.contrib import admin

from .models import Inspection


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ["property", "prospect_name", "agent", "tenant", "scheduled_at", "status"]
    list_filter = ["status"]
    list_select_related = ["property", "agent", "tenant"]
    raw_id_fields = ["property", "agent", "tenant", "cancelled_by"]
    readonly_fields = ["status", "confirmed_at", "completed_at", "cancelled_at", "cancelled_by"]
