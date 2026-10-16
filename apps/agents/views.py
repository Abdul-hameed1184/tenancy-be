from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import AgentProfileSerializer
from apps.common.cache import cached
from apps.common.permissions import IsAdmin

from . import selectors, services
from .models import AgentProfile

TAGS = ["agents"]
PRIVATE_FIELDS = ("passportDocUrl", "thirdPartyCheckRef")


AGENT_CACHE_TTL = 120


def redact(row: dict, viewer) -> dict:
    """Identity-document fields are for admins and the agent themself only."""
    is_privileged = getattr(viewer, "is_authenticated", False) and (
        viewer.is_admin or str(viewer.pk) == str(row["id"])
    )
    if is_privileged:
        return row
    return {k: v for k, v in row.items() if k not in PRIVATE_FIELDS}


class AgentListView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=TAGS,
        parameters=[
            OpenApiParameter(
                "verificationStatus",
                str,
                enum=[c for c, _ in AgentProfile.VerificationStatus.choices],
            )
        ],
        responses={200: AgentProfileSerializer(many=True)},
    )
    def get(self, request):
        status = request.query_params.get("verificationStatus")
        if status and status not in AgentProfile.VerificationStatus.values:
            raise ValidationError({"verificationStatus": ["Not a valid status."]})

        def produce():
            qs = selectors.agent_profiles()
            if status:
                if status == AgentProfile.VerificationStatus.VERIFIED:
                    # TEMPORARY: email verification is the current source of truth for the
                    # verified-agent directory until profile verification is reconciled.
                    # Legacy profile-only filter: agent_profile__verification_status=status
                    qs = qs.filter(email_verified_at__isnull=False)
                else:
                    qs = qs.filter(agent_profile__verification_status=status)
            return AgentProfileSerializer(qs, many=True).data

        # Cache the full representation once; strip private fields per viewer afterwards.
        rows = cached("agents", "list", {"status": status or ""}, AGENT_CACHE_TTL, produce)
        return Response([redact(row, request.user) for row in rows])


class AgentDetailView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(tags=TAGS, responses={200: AgentProfileSerializer})
    def get(self, request, agent_id):
        def produce():
            agent = selectors.agent_profiles().filter(pk=agent_id).first()
            return AgentProfileSerializer(agent).data if agent else {}

        row = cached("agents", "detail", {"pk": agent_id}, AGENT_CACHE_TTL, produce)
        if not row:
            raise NotFound("Agent not found.")
        return Response(redact(row, request.user))


class PendingVerificationsView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(tags=TAGS, responses={200: AgentProfileSerializer(many=True)})
    def get(self, request):
        qs = selectors.agent_profiles().filter(
            agent_profile__verification_status=AgentProfile.VerificationStatus.PENDING
        )
        return Response(AgentProfileSerializer(qs, many=True).data)


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[
            AgentProfile.VerificationStatus.VERIFIED,
            AgentProfile.VerificationStatus.REJECTED,
        ]
    )


class VerificationDecisionView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(tags=TAGS, request=DecisionSerializer, responses={200: AgentProfileSerializer})
    def post(self, request, agent_id):
        body = DecisionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            services.decide_verification(
                agent_id=agent_id,
                decision=body.validated_data["decision"],
                admin=request.user,
                request=request,
            )
        except AgentProfile.DoesNotExist as exc:
            raise NotFound("Agent not found.") from exc
        agent = get_object_or_404(selectors.agent_profiles(), pk=agent_id)
        return Response(AgentProfileSerializer(agent).data)
