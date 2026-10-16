"""
ASGI entrypoint: one process serves HTTP (Django/DRF) and WebSockets (Channels).

    websocket -> OriginValidator -> TicketAuthMiddleware -> URLRouter -> consumer

OriginValidator matters because CORS does not apply to WebSockets: without it any website
could open a socket to this API from a victim's browser (cross-site WebSocket hijacking).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

# Initialise Django (apps, settings) before importing anything that touches models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.common.ws import TicketAuthMiddleware  # noqa: E402

from .routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": OriginValidator(
            TicketAuthMiddleware(URLRouter(websocket_urlpatterns)),
            settings.CORS_ALLOWED_ORIGINS,
        ),
    }
)
