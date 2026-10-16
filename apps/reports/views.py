from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.permissions import HasRole, IsAdmin, ScopedQuerysetMixin

from . import services
from .models import Report
from .serializers import FileReportSerializer, ReportSerializer

TAGS = ["reports"]


def visible_to(user):
    qs = Report.objects.order_by("-created_at")
    if user.is_admin:
        return qs
    if user.is_landlord:
        return qs.filter(reported_by=user)  # "landlord (own)": the reports they filed
    return qs.none()


class ReportFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Report.Status.choices)
    type = filters.ChoiceFilter(choices=Report.Type.choices)
    reportedById = filters.UUIDFilter(field_name="reported_by_id")

    class Meta:
        model = Report
        fields = ["status", "type", "reportedById"]


@extend_schema_view(
    list=extend_schema(tags=TAGS),
    retrieve=extend_schema(tags=TAGS),
    create=extend_schema(
        tags=TAGS, request=FileReportSerializer, responses={201: ReportSerializer}
    ),
)
class ReportViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    visible_to = staticmethod(visible_to)
    serializer_class = ReportSerializer
    filterset_class = ReportFilter

    def get_permissions(self):
        if self.action == "list":
            return [HasRole("admin", "landlord")()]
        if self.action == "create":
            return [HasRole("landlord", "tenant")()]
        return [IsAdmin()]  # retrieve, resolve

    def create(self, request):
        body = FileReportSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            report = services.file_report(
                reporter=request.user,
                type=data["type"],
                target_id=data["targetId"],
                reason=data["reason"],
                request=request,
            )
        except services.InvalidTarget as exc:
            raise ValidationError({"targetId": [str(exc)]}) from exc
        return Response(ReportSerializer(report).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=TAGS, request=None, responses={200: ReportSerializer})
    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        report = self.get_object()
        resolved = services.resolve(report=report, admin=request.user, request=request)
        return Response(ReportSerializer(resolved).data)
