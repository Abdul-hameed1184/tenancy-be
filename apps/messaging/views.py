from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasRole, ensure_self

from . import selectors, services
from .serializers import (
    MessageContactSerializer,
    MessageSerializer,
    MessageThreadSerializer,
    SendMessageSerializer,
    StartThreadSerializer,
)

TAGS = ["messages"]
ANY_ROLE = HasRole("admin", "landlord", "agent", "tenant")


class ThreadListView(APIView):
    permission_classes = [ANY_ROLE]

    @extend_schema(
        tags=TAGS,
        parameters=[OpenApiParameter("userId", str, description="Must be your own id")],
        responses={200: MessageThreadSerializer(many=True)},
    )
    def get(self, request):
        ensure_self(request.user, request.query_params.get("userId"), what="threads")
        threads = selectors.threads_for(request.user)
        return Response(MessageThreadSerializer(threads, many=True).data)


class InitializeContactThreadsView(APIView):
    permission_classes = [ANY_ROLE]

    @extend_schema(tags=TAGS, responses={204: None})
    def post(self, request):
        services.initialize_contact_threads(user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ThreadMessagesView(APIView):
    permission_classes = [ANY_ROLE]

    def _require_membership(self, request, thread_id):
        # Non-members get 404, not 403: a thread's existence is private too.
        if not selectors.is_participant(request.user.pk, thread_id):
            raise NotFound("Thread not found.")

    @extend_schema(tags=TAGS, responses={200: MessageSerializer(many=True)})
    def get(self, request, thread_id):
        self._require_membership(request, thread_id)
        return Response(MessageSerializer(selectors.messages_in(thread_id), many=True).data)

    @extend_schema(tags=TAGS, request=SendMessageSerializer, responses={201: MessageSerializer})
    def post(self, request, thread_id):
        self._require_membership(request, thread_id)
        body = SendMessageSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        ensure_self(request.user, body.validated_data.get("senderId"), what="messages")
        try:
            message = services.send_message(
                thread_id=thread_id, sender=request.user, body=body.validated_data["body"]
            )
        except services.NotParticipant as exc:  # removed between the check and the send
            raise NotFound("Thread not found.") from exc
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ThreadReadView(APIView):
    permission_classes = [ANY_ROLE]

    @extend_schema(tags=TAGS, request=None, responses={204: None})
    def post(self, request, thread_id):
        try:
            services.mark_thread_read(thread_id=thread_id, user=request.user)
        except services.NotParticipant as exc:
            raise NotFound("Thread not found.") from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class PrimaryContactsView(APIView):
    permission_classes = [ANY_ROLE]

    @extend_schema(tags=TAGS, responses={200: MessageContactSerializer(many=True)})
    def get(self, request):
        contacts = selectors.primary_contacts_for(request.user)
        return Response(MessageContactSerializer(contacts, many=True).data)


class StartThreadView(APIView):
    permission_classes = [ANY_ROLE]

    @extend_schema(
        tags=TAGS,
        request=StartThreadSerializer,
        responses={200: MessageThreadSerializer},
    )
    def post(self, request):
        body = StartThreadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            thread = services.start_thread(
                user=request.user,
                recipient_id=body.validated_data["recipientId"],
                property_id=body.validated_data["propertyId"],
            )
        except services.NotParticipant as exc:
            raise NotFound("Contact not found in your property relationships.") from exc
        thread.participant_ids = list(thread.participants.values_list("pk", flat=True))
        return Response(MessageThreadSerializer(thread).data, status=status.HTTP_200_OK)
