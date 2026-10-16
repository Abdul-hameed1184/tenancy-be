"""
Additive endpoints (not in the frontend contract yet): the in-app notification feed.

The feed is capped at the newest MAX_FEED items so it stays bounded as history grows;
`?unread=true` narrows to unread ones.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsVerified

from . import services
from .models import Notification
from .serializers import NotificationSerializer

TAGS = ["notifications"]
MAX_FEED = 100


class NotificationListView(APIView):
    permission_classes = [IsVerified]

    @extend_schema(
        tags=TAGS,
        parameters=[OpenApiParameter("unread", bool)],
        responses={200: NotificationSerializer(many=True)},
    )
    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user).order_by("-created_at")
        if request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)
        return Response(NotificationSerializer(qs[:MAX_FEED], many=True).data)


class MarkReadView(APIView):
    permission_classes = [IsVerified]

    @extend_schema(tags=TAGS, request=None, responses={200: NotificationSerializer})
    def post(self, request, notification_id):
        services.mark_read(request.user, notification_id)
        notification = Notification.objects.filter(
            pk=notification_id, recipient=request.user
        ).first()
        if notification is None:
            raise NotFound("Notification not found.")
        return Response(NotificationSerializer(notification).data)


class _UpdatedCount(serializers.Serializer):
    updated = serializers.IntegerField()


class MarkAllReadView(APIView):
    permission_classes = [IsVerified]

    @extend_schema(tags=TAGS, request=None, responses={200: _UpdatedCount})
    def post(self, request):
        return Response(
            {"updated": services.mark_all_read(request.user)}, status=status.HTTP_200_OK
        )
