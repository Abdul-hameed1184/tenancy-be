from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.common.permissions import IsVerified

from . import cloudinary


class UploadsUnavailable(APIException):
    status_code = 503
    default_detail = "Image uploads aren't configured on this server."
    default_code = "uploads_unavailable"


class UploadSignatureThrottle(UserRateThrottle):
    scope = "upload_signature"


class SignatureRequestSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=sorted(cloudinary.PURPOSES))


SignatureResponse = inline_serializer(
    "UploadSignature",
    {
        "uploadUrl": serializers.URLField(),
        "fields": serializers.DictField(child=serializers.CharField()),
        "maxBytes": serializers.IntegerField(),
        "allowedFormats": serializers.ListField(child=serializers.CharField()),
        "expiresAt": serializers.IntegerField(),
    },
)


class UploadSignatureView(APIView):
    """
    Additive: authorise one direct-to-Cloudinary image upload.

    POST the file as multipart/form-data to `uploadUrl`, with every key/value of `fields`
    plus `file`. Use the returned `secure_url` in the API (property photos, avatarUrl).
    """

    permission_classes = [IsVerified]
    throttle_classes = [UploadSignatureThrottle]

    @extend_schema(
        tags=["uploads"], request=SignatureRequestSerializer, responses={200: SignatureResponse}
    )
    def post(self, request):
        body = SignatureRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        purpose = body.validated_data["purpose"]
        if request.user.role not in cloudinary.PURPOSES[purpose].roles:
            raise PermissionDenied("You can't upload this kind of image.")
        try:
            return Response(cloudinary.signed_upload(request.user, purpose))
        except cloudinary.UploadsNotConfigured as exc:
            raise UploadsUnavailable from exc
