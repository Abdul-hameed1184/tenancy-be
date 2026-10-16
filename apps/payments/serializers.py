from rest_framework import serializers

from apps.accounts.serializers import OmitEmptyMixin
from apps.common.fields import ContractDateField

from .models import PaymentEntry


class PaymentEntrySerializer(OmitEmptyMixin, serializers.ModelSerializer):
    tenancyId = serializers.UUIDField(source="tenancy_id", read_only=True)
    dueDate = ContractDateField(source="due_date", read_only=True)
    paidDate = ContractDateField(source="paid_date", read_only=True, allow_null=True)
    loggedByAgentId = serializers.UUIDField(source="logged_by_id", read_only=True)
    loggedAt = serializers.DateTimeField(source="logged_at", read_only=True)

    omit_if_empty = ("note",)

    class Meta:
        model = PaymentEntry
        fields = [
            "id",
            "tenancyId",
            "amount",
            "dueDate",
            "paidDate",
            "method",
            "loggedByAgentId",
            "loggedAt",
            "status",
            "note",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["paidDate"] = data.get("paidDate")  # always present: `string | null`
        return data


class LogPaymentSerializer(serializers.Serializer):
    """`loggedByAgentId` is accepted for compatibility and ignored: the logger is the token."""

    amount = serializers.IntegerField(min_value=1, max_value=10**12)
    dueDate = ContractDateField(source="due_date")
    paidDate = ContractDateField(source="paid_date", allow_null=True, required=False)
    method = serializers.ChoiceField(choices=PaymentEntry.Method.choices)
    status = serializers.ChoiceField(choices=PaymentEntry.Status.choices)
    loggedByAgentId = serializers.CharField(required=False, write_only=True)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate(self, attrs):
        attrs.pop("loggedByAgentId", None)
        paid = attrs["status"] == PaymentEntry.Status.PAID
        if paid and not attrs.get("paid_date"):
            raise serializers.ValidationError({"paidDate": ["Required when status is paid."]})
        if not paid and attrs.get("paid_date"):
            raise serializers.ValidationError(
                {"paidDate": ["Only paid entries can have a paid date."]}
            )
        return attrs
