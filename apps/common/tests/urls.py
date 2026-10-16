from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.routers import OptionalSlashRouter, optional_slash


class EchoView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        return Response({"received": request.data})


class ItemViewSet(viewsets.ViewSet):
    authentication_classes = []
    permission_classes = []

    def list(self, request):
        return Response([])

    def retrieve(self, request, pk=None):
        return Response({"id": pk})


router = OptionalSlashRouter()
router.register("items", ItemViewSet, basename="item")

urlpatterns = [*optional_slash("echo", EchoView.as_view()), *router.urls]
