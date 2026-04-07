"""
apps/chat/urls.py
=================
HTTP URL routing for the chat module's REST endpoints.

These patterns are mounted at /api/chat/ via api/chat/urls.py,
which is included by the master api/urls.py router.

WebSocket routes are defined separately in apps/chat/routing.py and
loaded by StallManagement/asgi.py — they are NOT included here.

Final HTTP URLs
---------------
    GET  /api/chat/inbox/                     All conversations + unread count
    GET  /api/chat/unread_count/              Total unread messages (badge count)
    POST /api/chat/send/                      Send a message (REST fallback)
    GET  /api/chat/history/<other_user_id>/   Conversation history + mark-read
    POST /api/chat/mark_read/<other_user_id>/ Explicitly mark messages as read

WebSocket URL (handled by asgi.py / routing.py)
------------------------------------------------
    ws://<host>/ws/chat/<other_user_id>/

URL ordering note
-----------------
Named endpoints ('inbox/', 'unread_count/', 'send/') must be declared
BEFORE '<int:other_user_id>/' to prevent Django treating them as integers.
"""

from django.urls import path
from .views import (
    ChatHistoryView,
    ChatSendView,
    ChatMarkReadView,
    ChatInboxView,
    ChatUnreadCountView,
)

app_name = 'chat'

urlpatterns = [
    # ── Named action endpoints (must precede <int:other_user_id>/) ───────
    # GET → list of all conversations with last message + unread count
    path('inbox/',        ChatInboxView.as_view(),       name='chat-inbox'),

    # GET → total unread count for the requesting user (nav badge)
    path('unread_count/', ChatUnreadCountView.as_view(), name='chat-unread-count'),

    # POST → send a message via REST (WS fallback)
    path('send/',         ChatSendView.as_view(),        name='chat-send'),

    # ── Per-conversation endpoints ───────────────────────────────────────
    # GET → message history (also marks received messages as read)
    path(
        'history/<int:other_user_id>/',
        ChatHistoryView.as_view(),
        name='chat-history',
    ),

    # POST → explicitly mark messages from <other_user_id> as read
    path(
        'mark_read/<int:other_user_id>/',
        ChatMarkReadView.as_view(),
        name='chat-mark-read',
    ),
]
