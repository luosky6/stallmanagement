"""
apps/chat/routing.py
====================
WebSocket URL routing for the chat module.

This module is imported by StallManagement/asgi.py and passed to the
URLRouter inside the ProtocolTypeRouter's 'websocket' handler.

WebSocket URL
-------------
    ws://<host>/ws/chat/<other_user_id>/

    <other_user_id> is the integer ID of the conversation partner.
    The consumer derives the canonical room name from this ID and the
    requesting user's own ID:
        room = chat_<min(self_id, other_id)>_<max(self_id, other_id)>

    Example:
        Customer (id=3) connecting to Stall Owner (id=2):
            ws://localhost:8000/ws/chat/2/
            → room: chat_2_3
            → group: group_chat_2_3

        Stall Owner (id=2) connecting to Customer (id=3):
            ws://localhost:8000/ws/chat/3/
            → room: chat_2_3   (same room, both join the same group)
            → group: group_chat_2_3

This file only defines websocket_urlpatterns — it does NOT call
include() or set an app_name, because it is consumed by Django Channels'
URLRouter, not Django's standard URL dispatcher.
"""

from django.urls import re_path
from .consumers import ChatConsumer

websocket_urlpatterns = [
    # ws://<host>/ws/chat/<other_user_id>/
    # other_user_id must be a positive integer
    re_path(
        r'^ws/chat/(?P<other_user_id>\d+)/$',
        ChatConsumer.as_asgi(),
        name='ws-chat',
    ),
]
