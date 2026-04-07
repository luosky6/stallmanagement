"""
api/chat/views.py
=================
Chat API sub-package — view registry and documentation.

This module re-exports all chat REST views from apps/chat/views.py
and serves as the single import point for the sub-package's urls.py.

Two transport layers
--------------------
The chat system uses two complementary delivery mechanisms:

  1. REST (this sub-package)
       - Load message HISTORY on page load before WebSocket delivers new ones
       - Send messages via REST as a fallback when WebSocket is unavailable
       - Mark messages as read (also happens automatically on WS connect)
       - Inbox summary with unread counts per conversation
       - Total unread count for the nav badge

  2. WebSocket (apps/chat/consumers.py + apps/chat/routing.py)
       - Real-time delivery of new messages as they are typed and sent
       - Replaces the frontend's simulated auto-reply setTimeout()
       - Connected via ws://<host>/ws/chat/<other_user_id>/
       - Handled by asgi.py — NOT routed through this file

Full API surface for /api/chat/
---------------------------------
Method  URL                                    Permission       Description
------  ------------------------------------   -------------    ---------------------
GET     /api/chat/inbox/                       Any auth user    All conversations the
                                                                user is part of, with
                                                                last message preview and
                                                                unread count per partner.
                                                                Ordered by most recent.
GET     /api/chat/unread_count/                Any auth user    Total unread message count
                                                                across all conversations.
                                                                Used for the nav badge.
POST    /api/chat/send/                        Any auth user    Send a message via REST
                                                                (WS fallback). Validates
                                                                role pairing rules.
GET     /api/chat/history/<other_user_id>/     Any auth user    Full conversation history
                                                                between the requesting
                                                                user and the partner.
                                                                Also marks received
                                                                messages as read.
POST    /api/chat/mark_read/<other_user_id>/   Any auth user    Explicitly mark all unread
                                                                messages FROM other_user_id
                                                                TO the requesting user
                                                                as read.

WebSocket URL (separate from REST)
------------------------------------
    ws://<host>/ws/chat/<other_user_id>/

    Handled by: apps.chat.consumers.ChatConsumer
    Registered in: apps.chat.routing.websocket_urlpatterns
    Loaded by:   StallManagement.asgi.application

Request / Response examples
----------------------------
GET /api/chat/inbox/
    Response (200):
        {
            "success": true,
            "data": {
                "total": 1,
                "results": [
                    {
                        "partner": {
                            "id": 2,
                            "username": "owner1",
                            "name": "Stall Owner Li",
                            "role": "stall_owner"
                        },
                        "last_message": {
                            "id":          3,
                            "content":     "I would like 20 units then...",
                            "create_time": "2024-11-27T10:02:00Z",
                            "is_read":     false,
                            "is_mine":     true
                        },
                        "unread_count": 0
                    }
                ]
            }
        }

GET /api/chat/unread_count/
    Response (200):
        {
            "success": true,
            "data": { "unread_count": 2 }
        }

POST /api/chat/send/
    Request body:
        { "receiver_id": 2, "content": "Hello, do you have sports pants?" }
    Success response (201):
        {
            "success": true,
            "code":    201,
            "message": "Message sent successfully.",
            "data": {
                "id": 4,
                "sender":   { "id": 3, "username": "customer1", ... },
                "receiver": { "id": 2, "username": "owner1", ... },
                "content":  "Hello, do you have sports pants?",
                "is_read":  false,
                "create_time": "2024-11-27T10:05:00Z"
            }
        }

GET /api/chat/history/2/
    Response (200):
        {
            "success": true,
            "data": {
                "total": 3,
                "partner": { "id": 2, "username": "owner1", "name": "Stall Owner Li", ... },
                "results": [
                    {
                        "id": 1,
                        "sender":   { "id": 3, "username": "customer1", ... },
                        "receiver": { "id": 2, "username": "owner1", ... },
                        "content":  "Hello, do you have sports pants available?",
                        "is_read":  true,
                        "create_time": "2024-11-27T10:00:00Z"
                    },
                    ...
                ]
            }
        }

Role pairing rules (enforced by ChatMessageSendSerializer)
-----------------------------------------------------------
Valid:
    customer    ↔  stall_owner   (primary use case)
    admin       ↔  any role      (admin can contact any user)

Invalid (rejected with 400):
    customer    ↔  customer      (customers cannot message each other)
    stall_owner ↔  stall_owner   (stall owners cannot message each other)

Query parameters for GET /api/chat/history/<other_user_id>/
    page        integer (default: 1)
    page_size   integer (default: 50, max: 200)
"""

# ---------------------------------------------------------------------------
# Re-exports — all logic lives in apps/chat/views.py
# ---------------------------------------------------------------------------
from apps.chat.views import (           # noqa: F401
    ChatHistoryView,
    ChatSendView,
    ChatMarkReadView,
    ChatInboxView,
    ChatUnreadCountView,
)


# ---------------------------------------------------------------------------
# ChatMessageViewSet — logical grouping for documentation and tooling
# ---------------------------------------------------------------------------
class ChatMessageViewSet:
    """
    Logical grouping of all chat REST views.

    Not a DRF ViewSet — uses APIView throughout for explicit control.
    This class is a registry for documentation tools and IDE navigation.

    REST Views
    ----------
    inbox           ChatInboxView           GET   /api/chat/inbox/
    unread_count    ChatUnreadCountView      GET   /api/chat/unread_count/
    send            ChatSendView            POST  /api/chat/send/
    history         ChatHistoryView         GET   /api/chat/history/<other_user_id>/
    mark_read       ChatMarkReadView        POST  /api/chat/mark_read/<other_user_id>/

    WebSocket Consumer (separate)
    -----------------------------
    ChatConsumer    apps.chat.consumers.ChatConsumer
    WS URL          ws://<host>/ws/chat/<other_user_id>/

    Typical frontend flow
    ---------------------
    1. User opens Chat tab.
    2. Frontend calls GET /api/chat/inbox/ to render the conversation list.
    3. User selects a conversation partner.
    4. Frontend calls GET /api/chat/history/<partner_id>/ to load prior messages.
       (This also marks received messages as read — clearing the unread badge.)
    5. Frontend opens WebSocket: ws://<host>/ws/chat/<partner_id>/
    6. New messages are delivered in real-time via the WebSocket.
    7. If the WebSocket drops, the frontend falls back to POST /api/chat/send/.
    8. On reconnect, GET /api/chat/history/ syncs any messages missed while offline.
    """

    inbox        = ChatInboxView
    unread_count = ChatUnreadCountView
    send         = ChatSendView
    history      = ChatHistoryView
    mark_read    = ChatMarkReadView