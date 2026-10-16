from django.contrib import admin

from .models import MaintenanceRequest


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ["issue_type", "property", "tenant", "priority", "status", "reported_at"]
    list_filter = ["status", "priority"]
    list_select_related = ["property", "tenant"]
    raw_id_fields = ["property", "tenant"]
    readonly_fields = ["status", "completed_at"]  # status changes go through the service
