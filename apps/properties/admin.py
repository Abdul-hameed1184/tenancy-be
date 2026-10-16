from django.contrib import admin

from .models import Property, PropertyAgentAssignment


class AssignmentInline(admin.TabularInline):
    model = PropertyAgentAssignment
    fk_name = "property"
    extra = 0
    fields = ["agent", "active", "assigned_at", "unassigned_at", "assigned_by"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False  # assignments go through the service, which keeps the invariant


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["title", "city", "status", "landlord", "price_annual", "featured"]
    list_filter = ["status", "featured", "city"]
    search_fields = ["title", "neighborhood", "city", "landlord__email"]
    list_select_related = ["landlord"]
    raw_id_fields = ["landlord"]
    inlines = [AssignmentInline]
