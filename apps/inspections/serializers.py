from django.utils import timezone
from rest_framework import serializers

from .models import Inspection


class InspectionSerializer(serializers.ModelSerializer):
    propertyId = serializers.UUIDField(source="property_id", read_only=True)
    tenantId = serializers.UUIDField(source="tenant_id", read_only=True)
    agentId = serializers.UUIDField(source="agent_id", read_only=True)
    prospectName = serializers.CharField(source="prospect_name", read_only=True)
    requestedAt = serializers.DateTimeField(source="requested_at", read_only=True)
    scheduledAt = serializers.DateTimeField(source="scheduled_at", read_only=True)

    class Meta:
        model = Inspection
        fields = [
            "id",
            "propertyId",
            "tenantId",
            "agentId",
            "prospectName",
            "requestedAt",
            "scheduledAt",
            "status",
        ]
        read_only_fields = fields


class RequestInspectionSerializer(serializers.Serializer):
    """`tenantId` is ignored (the token decides); `agentId` is checked against the property."""

    propertyId = serializers.UUIDField()
    tenantId = serializers.CharField(required=False, write_only=True)
    agentId = serializers.UUIDField(required=False)
    prospectName = serializers.CharField(max_length=150)
    scheduledAt = serializers.DateTimeField()

    def validate_scheduledAt(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("Choose a time in the future.")
        return value
