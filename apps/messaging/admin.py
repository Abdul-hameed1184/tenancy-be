from django.contrib import admin

from .models import Message, MessageThread, ThreadParticipant


class ParticipantInline(admin.TabularInline):
    model = ThreadParticipant
    extra = 2
    raw_id_fields = ["user"]


@admin.register(MessageThread)
class MessageThreadAdmin(admin.ModelAdmin):
    """The contract has no create-thread endpoint; threads are opened here (or by seeding)."""

    list_display = ["id", "property", "last_message_at", "created_at"]
    raw_id_fields = ["property"]
    inlines = [ParticipantInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["thread", "sender", "sent_at"]
    list_select_related = ["sender"]
    raw_id_fields = ["thread", "sender"]
