from django.contrib import admin

from .models import AgentProfile


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "agency", "verification_status", "trust_score"]
    list_filter = ["verification_status"]
    search_fields = ["user__email", "user__name", "agency"]
    list_select_related = ["user"]
    raw_id_fields = ["user"]
