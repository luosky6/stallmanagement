"""
ASGI Configuration for StallManagement
=======================================
This module exposes the ASGI callable as a module-level variable named
``application``.  It handles BOTH standard HTTP requests and WebSocket
connections through Django Channels.

Protocol routing
----------------
                          ┌─────────────────────────────────┐
  Client request          │         ASGI application         │
  ──────────────►  ──►    │  ProtocolTypeRouter              │
                          │   ├─ "http"  → Django (HTTP)     │
                          │   └─ "websocket"                  │
                          │        └─ AuthMiddlewareStack     │
                          │             └─ URLRouter          │
                          │                  └─ ChatConsumer  │
                          └─────────────────────────────────┘

WebSocket URL
-------------
    ws://<host>/ws/chat/<room_name>/

    <room_name> is built by the Vue frontend as:
        "user_<smaller_id>_<larger_id>"
    This ensures both participants join the same channel group regardless
    of who initiates the connection.

Production server
-----------------
    daphne StallManagement.asgi:application --port 8000 --bind 0.0.0.0
    # or
    uvicorn StallManagement.asgi:application --host 0.0.0.0 --port 8000
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'StallManagement.settings')

# Django must be set up before importing anything that touches models or apps.
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

# Import WebSocket URL patterns from the chat app.
# apps/chat/routing.py defines:
#   websocket_urlpatterns = [
#       path('ws/chat/<str:room_name>/', ChatConsumer.as_asgi()),
#   ]
from apps.chat.routing import websocket_urlpatterns

# Standard Django ASGI application for HTTP requests.
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({

    # ── HTTP ──────────────────────────────────────────────────────────
    # All normal Django views, DRF endpoints, and static file serving
    # are routed through the standard ASGI handler.
    "http": django_asgi_app,

    # ── WebSocket ─────────────────────────────────────────────────────
    # AllowedHostsOriginValidator  — rejects connections whose Origin
    #   header is not in ALLOWED_HOSTS (CSRF-equivalent for WebSockets).
    # AuthMiddlewareStack          — populates scope["user"] from the
    #   Django session cookie, so ChatConsumer can identify the sender.
    # URLRouter                    — dispatches to the correct consumer
    #   based on the WebSocket path.
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),

})
