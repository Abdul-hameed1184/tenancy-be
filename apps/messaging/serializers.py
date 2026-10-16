from rest_framework import serializers

from apps.accounts.serializers import OmitEmptyMixin

from .models import Message, MessageThread


class MessageThreadSerializer(OmitEmptyMixin, serializers.ModelSerializer):
    participantIds = serializers.ListField(
        child=serializers.UUIDField(), source="participant_ids", read_only=True
    )
    propertyId = serializers.UUIDField(source="property_id", read_only=True, allow_null=True)
    lastMessageAt = serializers.DateTimeField(source="last_message_at", read_only=True)
    unreadCount = serializers.IntegerField(source="unread_count", read_only=True)
    lastMessagePreview = serializers.CharField(
        source="last_message_preview", read_only=True, allow_null=True
    )

    omit_if_empty = ("propertyId", "lastMessagePreview")

    class Meta:
        model = MessageThread
        fields = [
            "id",
            "participantIds",
            "propertyId",
            "lastMessageAt",
            "unreadCount",
            "lastMessagePreview",
        ]
        read_only_fields = fields


class MessageSerializer(OmitEmptyMixin, serializers.ModelSerializer):
    threadId = serializers.UUIDField(source="thread_id", read_only=True)
    senderId = serializers.UUIDField(source="sender_id", read_only=True)
    sentAt = serializers.DateTimeField(source="sent_at", read_only=True)
    readAt = serializers.DateTimeField(source="read_at", read_only=True, allow_null=True)

    omit_if_empty = ("readAt",)

    class Meta:
        model = Message
        fields = ["id", "threadId", "senderId", "body", "sentAt", "readAt"]
        read_only_fields = fields


class SendMessageSerializer(serializers.Serializer):
    """Shared by REST and WebSocket input. `senderId` is optional over WebSocket."""

    senderId = serializers.UUIDField(required=False)
    body = serializers.CharField(max_length=5000, trim_whitespace=True)


class MessageContactSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    role = serializers.CharField()
    propertyId = serializers.UUIDField()
    propertyTitle = serializers.CharField()


class StartThreadSerializer(serializers.Serializer):
    recipientId = serializers.UUIDField()
    propertyId = serializers.UUIDField()
