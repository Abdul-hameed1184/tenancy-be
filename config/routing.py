from django.urls import path

from apps.messaging.consumers import ThreadConsumer
from apps.notifications.consumers import NotificationConsumer

websocket_urlpatterns = [
    path("ws/threads/<uuid:thread_id>/", ThreadConsumer.as_asgi()),
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]
