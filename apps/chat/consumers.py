"""
apps/chat/consumers.py
======================
WebSocket consumer for real-time chat.

This consumer replaces the frontend's simulated auto-reply:

    Frontend (before):
        setTimeout(() => {
            this.messages.push({ from: 'Stall Owner', text: 'Thanks...' })
        }, 700)

    Backend (now):
        ChatConsumer receives the message, saves it to the DB, and
        broadcasts it to everyone in the channel group — including
        the OTHER user's open browser tab — in real-time.

Connection lifecycle
--------------------
    connect()
        - Verifies the user is authenticated (AnonymousUser is rejected).
        - Derives the room_name from the URL path parameter (other_user_id).
        - Adds the socket to the channel group for that room.
        - Accepts the WebSocket connection.

    receive()
        - Receives a JSON message from the client browser.
        - Validates the payload (must have 'content').
        - Saves a ChatMessage record to the database.
        - Broadcasts the serialised message to the channel group.
          This delivers the message to BOTH users' open connections
          (the sender sees their own message confirmed; the receiver
          sees it appear in real-time).

    disconnect()
        - Removes the socket from the channel group.

    chat_message() [group event handler]
        - Called by the channel layer when another consumer in the same
          group calls group_send().
        - Forwards the message payload to the WebSocket client.

WebSocket URL
-------------
    ws://<host>/ws/chat/<other_user_id>/

    <other_user_id> is the ID of the conversation partner.
    The consumer combines the current user's ID and the partner's ID
    to form a canonical room name using ChatMessage.room_name().

Authentication
--------------
    AuthMiddlewareStack in asgi.py populates scope['user'] from the
    Django session cookie.  If scope['user'] is AnonymousUser the
    consumer closes the connection immediately with code 4001.

Channel layer
-------------
    Uses Redis via channels_redis (configured in settings.CHANNEL_LAYERS).
    In-memory channel layer is NOT suitable for production (single process
    only) — ensure REDIS_URL is set in the .env file.
"""

import json
import logging
from datetime import datetime

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from .models import ChatMessage
from .serializers import ChatMessageWebSocketSerializer

logger = logging.getLogger('apps')


class ChatConsumer(AsyncWebsocketConsumer):
    """
    Async WebSocket consumer for one-to-one chat between two users.

    The consumer is instantiated per WebSocket connection.  All DB
    operations are wrapped with database_sync_to_async to avoid blocking
    the async event loop.
    """

    # ------------------------------------------------------------------
    # Connect
    # ------------------------------------------------------------------
    async def connect(self):
        """
        Called when the WebSocket handshake is initiated.

        Steps:
        1. Reject anonymous users immediately.
        2. Parse <other_user_id> from the URL route.
        3. Validate the partner user exists.
        4. Compute the canonical room name.
        5. Join the channel group.
        6. Accept the connection.
        """
        self.user = self.scope.get('user')

        # ── Reject unauthenticated connections ──────────────────────────
        if not self.user or not self.user.is_authenticated:
            logger.warning('ChatConsumer: rejected anonymous WebSocket connection.')
            await self.close(code=4001)
            return

        # ── Parse the partner user ID from the URL ──────────────────────
        try:
            self.other_user_id = int(self.scope['url_route']['kwargs']['other_user_id'])
        except (KeyError, ValueError, TypeError):
            logger.warning(
                'ChatConsumer: invalid other_user_id in URL for user "%s".',
                self.user.username,
            )
            await self.close(code=4002)
            return

        # ── Verify the partner user exists ──────────────────────────────
        partner = await self._get_user(self.other_user_id)
        if partner is None:
            logger.warning(
                'ChatConsumer: partner user id=%d not found; '
                'closing connection for user "%s".',
                self.other_user_id, self.user.username,
            )
            await self.close(code=4003)
            return

        self.partner = partner

        # ── Compute canonical room name ──────────────────────────────────
        self.room_name  = ChatMessage.room_name(self.user.id, self.other_user_id)
        self.room_group = f'group_{self.room_name}'

        # ── Join channel group ───────────────────────────────────────────
        await self.channel_layer.group_add(
            self.room_group,
            self.channel_name,
        )

        await self.accept()

        logger.info(
            'ChatConsumer: user "%s" connected to room "%s".',
            self.user.username, self.room_name,
        )

        # ── Mark unread messages from the partner as read on connect ─────
        # (covers the case where the user opens the chat window and
        # there are already unread messages from the partner)
        await self._mark_messages_as_read(
            sender_id   = self.other_user_id,
            receiver_id = self.user.id,
        )

    # ------------------------------------------------------------------
    # Disconnect
    # ------------------------------------------------------------------
    async def disconnect(self, close_code):
        """Called when the WebSocket is closed (browser tab closed, network drop, etc.)."""
        if hasattr(self, 'room_group'):
            await self.channel_layer.group_discard(
                self.room_group,
                self.channel_name,
            )
        logger.info(
            'ChatConsumer: user "%s" disconnected from room "%s" (code=%s).',
            getattr(self.user, 'username', 'unknown'),
            getattr(self, 'room_name', 'unknown'),
            close_code,
        )

    # ------------------------------------------------------------------
    # Receive — browser → server
    # ------------------------------------------------------------------
    async def receive(self, text_data):
        """
        Called when the client sends a WebSocket message.

        Expected JSON payload:
            { "content": "Hello, do you have sports pants available?" }

        Steps:
        1. Parse and validate the JSON payload.
        2. Save the ChatMessage to the database.
        3. Broadcast the serialised message to the channel group.
           (Both the sender and receiver get it via chat_message().)
        """
        # ── Parse payload ────────────────────────────────────────────────
        try:
            data    = json.loads(text_data)
            content = data.get('content', '').strip()
        except (json.JSONDecodeError, AttributeError):
            await self._send_error('Invalid JSON payload.')
            return

        if not content:
            await self._send_error('Message content cannot be blank.')
            return

        if len(content) > 5000:
            await self._send_error('Message content exceeds 5000 characters.')
            return

        # ── Persist to database ──────────────────────────────────────────
        message = await self._save_message(
            sender_id   = self.user.id,
            receiver_id = self.other_user_id,
            content     = content,
        )

        if message is None:
            await self._send_error('Failed to save message. Please try again.')
            return

        # ── Serialise for broadcast ──────────────────────────────────────
        message_data = await self._serialise_message(message)

        # ── Broadcast to the channel group ───────────────────────────────
        # Both the sender's and receiver's connections call chat_message()
        await self.channel_layer.group_send(
            self.room_group,
            {
                'type':    'chat_message',   # routes to self.chat_message()
                'message': message_data,
            },
        )

        logger.debug(
            'ChatConsumer: user "%s" sent message id=%d in room "%s".',
            self.user.username, message.id, self.room_name,
        )

    # ------------------------------------------------------------------
    # chat_message — channel group event handler (server → browser)
    # ------------------------------------------------------------------
    async def chat_message(self, event):
        """
        Called by the channel layer when group_send() delivers a
        'chat_message' type event to this connection.

        Forwards the message payload to the connected WebSocket client
        as a JSON string.
        """
        await self.send(text_data=json.dumps({
            'type':    'chat_message',
            'message': event['message'],
        }))

    # ------------------------------------------------------------------
    # read_receipt — group event for marking messages read
    # ------------------------------------------------------------------
    async def read_receipt(self, event):
        """
        Notifies the sender that the receiver has read their messages.
        Sent when the receiver opens/connects to the chat window.
        """
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'data': event['data'],
        }))

    # ------------------------------------------------------------------
    # Private helpers — all DB operations use database_sync_to_async
    # ------------------------------------------------------------------
    @database_sync_to_async
    def _get_user(self, user_id):
        """Fetch a user by PK; return None if not found."""
        from apps.user.models import User
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def _save_message(self, sender_id, receiver_id, content):
        """Create and return a ChatMessage record."""
        try:
            return ChatMessage.objects.create(
                sender_id   = sender_id,
                receiver_id = receiver_id,
                content     = content,
                is_read     = False,
            )
        except Exception as exc:
            logger.error(
                'ChatConsumer._save_message: DB error: %s', exc, exc_info=True
            )
            return None

    @database_sync_to_async
    def _serialise_message(self, message):
        """
        Serialise a ChatMessage instance to a plain dict for JSON broadcast.
        Must be called inside database_sync_to_async because the serializer
        accesses related fields (sender.username, sender.name).
        """
        message_with_relations = (
            ChatMessage.objects
            .select_related('sender', 'receiver')
            .get(pk=message.pk)
        )
        data = ChatMessageWebSocketSerializer(message_with_relations).data
        # Convert datetime to ISO string for JSON serialisation
        if hasattr(data.get('create_time'), 'isoformat'):
            data['create_time'] = data['create_time'].isoformat()
        return dict(data)

    @database_sync_to_async
    def _mark_messages_as_read(self, sender_id, receiver_id):
        """
        Mark all unread messages from sender to receiver as read.
        Called on connect to clear the unread badge when the user
        opens the chat window.

        Also broadcasts a read_receipt event to the sender so their
        UI can show the double-tick / read indicator.
        """
        updated = ChatMessage.objects.filter(
            sender_id   = sender_id,
            receiver_id = receiver_id,
            is_read     = False,
        ).update(is_read=True)

        return updated

    async def _send_error(self, message: str):
        """Send an error frame to the client without closing the connection."""
        await self.send(text_data=json.dumps({
            'type':    'error',
            'message': message,
        }))
