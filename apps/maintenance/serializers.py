from rest_framework import serializers

from .models import MaintenanceRequest


class MaintenanceRequestSerializer(serializers.ModelSerializer):
    propertyId = serializers.UUIDField(source="property_id", read_only=True)
    tenantId = serializers.UUIDField(source="tenant_id", read_only=True)
    issueType = serializers.CharField(source="issue_type", read_only=True)
    reportedAt = serializers.DateTimeField(source="reported_at", read_only=True)

    class Meta:
        model = MaintenanceRequest
        fields = [
            "id",
            "propertyId",
            "tenantId",
            "issueType",
            "description",
            "priority",
            "status",
            "reportedAt",
        ]
        read_only_fields = fields


class CreateMaintenanceSerializer(serializers.Serializer):
    """`tenantId` is accepted and ignored; the reporter is the authenticated tenant."""

    propertyId = serializers.UUIDField()
    tenantId = serializers.CharField(required=False, write_only=True)
    issueType = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=5000)
    priority = serializers.ChoiceField(choices=MaintenanceRequest.Priority.choices)


class UpdateMaintenanceStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MaintenanceRequest.Status.choices)
