from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: the audit trail is evidence, not editable data."""

    list_display = ["created_at", "action", "actor", "entity_type", "entity_id", "ip_address"]
    list_filter = ["action", "entity_type"]
    search_fields = ["entity_id", "actor__email"]
    list_select_related = ["actor"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
