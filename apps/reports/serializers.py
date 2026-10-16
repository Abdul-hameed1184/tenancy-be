from rest_framework import serializers

from .models import Report


class ReportSerializer(serializers.ModelSerializer):
    targetId = serializers.UUIDField(source="target_id", read_only=True)
    reportedById = serializers.UUIDField(source="reported_by_id", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Report
        fields = ["id", "type", "targetId", "reason", "reportedById", "status", "createdAt"]
        read_only_fields = fields


class FileReportSerializer(serializers.Serializer):
    """`reportedById` is accepted and ignored: the reporter is the token's user."""

    type = serializers.ChoiceField(choices=Report.Type.choices)
    targetId = serializers.UUIDField()
    reason = serializers.CharField(max_length=2000, trim_whitespace=True)
    reportedById = serializers.CharField(required=False, write_only=True)
