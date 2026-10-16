from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["recipient", "type", "title", "is_read", "emailed_at", "created_at"]
    list_filter = ["type", "is_read"]
    list_select_related = ["recipient"]
    search_fields = ["recipient__email", "title"]
    raw_id_fields = ["recipient"]
