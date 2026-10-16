from django.contrib import admin

from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["type", "reported_by", "status", "created_at", "resolved_at"]
    list_filter = ["type", "status"]
    list_select_related = ["reported_by"]
    raw_id_fields = ["target_property", "target_user", "reported_by", "resolved_by"]
    readonly_fields = ["status", "resolved_at", "resolved_by"]  # resolve via the API service
