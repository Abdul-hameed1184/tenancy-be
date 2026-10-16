from rest_framework import serializers

from .models import Property, PropertyAgentAssignment, PropertyTenantRequest


class PhotoURLField(serializers.URLField):
    """Photo URLs must be https: mixed content is blocked on an https frontend."""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not value.lower().startswith("https://"):
            raise serializers.ValidationError("Photo URLs must use https.")
        return value


class VideoURLField(serializers.URLField):
    """Video URLs must use https: mixed content is blocked on an https frontend."""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not value.lower().startswith("https://"):
            raise serializers.ValidationError("Video URLs must use https.")
        return value


class PropertySerializer(serializers.ModelSerializer):
    """
    The contract's `Property`. Expects querysets from selectors.with_active_agent(), which
    provides `active_agent_id` for `agentId` (REQUIRED in responses, null when unmanaged).
    """

    photos = serializers.ListField(child=PhotoURLField(max_length=500), max_length=20)
    videos = serializers.ListField(
        child=VideoURLField(max_length=500), max_length=10, required=False
    )
    sqft = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    priceAnnual = serializers.IntegerField(source="price_annual", min_value=1)
    landlordId = serializers.UUIDField(source="landlord_id", read_only=True)
    occupancyRate = serializers.IntegerField(
        source="occupancy_rate", min_value=0, max_value=100, read_only=True
    )
    agentId = serializers.UUIDField(source="active_agent_id", read_only=True, allow_null=True)

    class Meta:
        model = Property
        fields = [
            "id",
            "title",
            "address",
            "city",
            "state",
            "neighborhood",
            "photos",
            "videos",
            "bedrooms",
            "bathrooms",
            "sqft",
            "priceAnnual",
            "status",
            "landlordId",
            "occupancyRate",
            "featured",
            "agentId",
        ]
        read_only_fields = ["id"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Guarantee the key exists even for an instance that wasn't annotated.
        data.setdefault("agentId", None)
        return data


class _OwnedPhotosMixin:
    """
    Photos on our Cloudinary account must come from the signed-upload flow for *this*
    landlord (their own folder). External https URLs remain allowed, as before.
    """

    def validate_photos(self, urls: list[str]) -> list[str]:
        from apps.uploads.cloudinary import InvalidUpload, assert_owned_upload, is_cloudinary_url

        request = self.context.get("request")
        for url in urls:
            if not is_cloudinary_url(url):
                continue
            try:
                assert_owned_upload(url, user=request.user, purpose="property_photo")
            except InvalidUpload as exc:
                raise serializers.ValidationError(str(exc)) from exc
        return urls


class _OwnedVideosMixin:
    def validate_videos(self, urls: list[str]) -> list[str]:
        from apps.uploads.cloudinary import InvalidUpload, assert_owned_upload, is_cloudinary_url

        request = self.context.get("request")
        for url in urls:
            if not is_cloudinary_url(url):
                continue
            try:
                assert_owned_upload(url, user=request.user, purpose="property_video")
            except InvalidUpload as exc:
                raise serializers.ValidationError(str(exc)) from exc
        return urls


class PropertyCreateSerializer(_OwnedPhotosMixin, _OwnedVideosMixin, PropertySerializer):
    """`landlordId` in the body is ignored: the owner is the authenticated landlord."""

    status = serializers.ChoiceField(
        choices=Property.Status.choices, default=Property.Status.LISTED
    )
    featured = serializers.BooleanField(default=False)


class PropertyUpdateSerializer(_OwnedPhotosMixin, _OwnedVideosMixin, PropertySerializer):
    """`Partial<Property>`: unknown and read-only keys (id, landlordId, agentId) are ignored."""

    occupancyRate = serializers.IntegerField(source="occupancy_rate", min_value=0, max_value=100)


class AssignAgentSerializer(serializers.Serializer):
    agentId = serializers.UUIDField()


class AgentAssignmentSerializer(serializers.ModelSerializer):
    propertyId = serializers.UUIDField(source="property_id", read_only=True)
    agentId = serializers.UUIDField(source="agent_id", read_only=True)
    assignedAt = serializers.DateTimeField(source="assigned_at", read_only=True)

    class Meta:
        model = PropertyAgentAssignment
        fields = ["id", "propertyId", "agentId", "assignedAt", "active"]
        read_only_fields = fields


class TenantCandidateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class TenantRequestCreateSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=PropertyTenantRequest.Action.choices)
    tenantId = serializers.UUIDField()
    unit = serializers.CharField(max_length=50, required=False, allow_blank=True)
    leaseStart = serializers.DateField(required=False)
    nextDueDate = serializers.DateField(required=False)

    def validate(self, attrs):
        if attrs["action"] == PropertyTenantRequest.Action.ASSIGN:
            required = {"unit", "leaseStart", "nextDueDate"}
            missing = required - attrs.keys()
            if missing:
                raise serializers.ValidationError(
                    {field: ["This field is required for an assignment request."] for field in missing}
                )
            if not attrs["unit"].strip():
                raise serializers.ValidationError({"unit": ["This field may not be blank."]})
            if attrs["nextDueDate"] < attrs["leaseStart"]:
                raise serializers.ValidationError(
                    {"nextDueDate": ["Next due date can't be before the lease start."]}
                )
        return attrs


class PropertyTenantRequestSerializer(serializers.ModelSerializer):
    propertyId = serializers.UUIDField(source="property_id", read_only=True)
    tenantId = serializers.UUIDField(source="tenant_id", read_only=True)
    tenantName = serializers.CharField(source="tenant.name", read_only=True)
    leaseStart = serializers.DateField(source="lease_start", read_only=True, allow_null=True)
    nextDueDate = serializers.DateField(source="next_due_date", read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = PropertyTenantRequest
        fields = [
            "id",
            "propertyId",
            "tenantId",
            "tenantName",
            "action",
            "status",
            "unit",
            "leaseStart",
            "nextDueDate",
            "createdAt",
        ]
        read_only_fields = fields


class TenantRequestDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
