"""
ASGI config: HTTP goes to Django, WebSockets to the live-update consumer.

https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Before importing anything that touches models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402
from django.conf import settings  # noqa: E402
from django.urls import path  # noqa: E402

from shows.console import supervisor  # noqa: E402
from shows.consumers import ProductionConsumer  # noqa: E402

websocket_urls = [path("ws/productions/<int:production_id>/", ProductionConsumer.as_asgi())]

router = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Only the frontend's own origins may open a socket.
        "websocket": OriginValidator(URLRouter(websocket_urls), settings.CORS_ALLOWED_ORIGINS),
    }
)


async def application(scope, receive, send):
    # Daphne has no startup hook, so the Eos console listeners start with the
    # first request or socket (see shows/console.py).
    if settings.EOS_LISTENERS and scope["type"] in ("http", "websocket"):
        supervisor.ensure_started()
    await router(scope, receive, send)
