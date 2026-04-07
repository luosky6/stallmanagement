"""
apps/chat/views.py
==================
REST API views for the chat module.

These HTTP endpoints complement the WebSocket consumer:

  WebSocket (consumers.py)
      Real-time delivery of new messages as they are sent.
      The browser keeps a persistent WS connection open while the
      chat tab is active.

  REST (this file)
      1. Load message HISTORY on page load (before WS delivers new ones).
      2. Send a message via REST (fallback if WS is unavailable).
      3. Mark messages as read (also triggered on WS connect, but REST
         allows explicit marking from the frontend).
      4. Inbox — summary of all conversations with unread counts.

Views
-----
ChatHistoryView         GET  /api/chat/history/<other_user_id>/    Conversation history
ChatSendView            POST /api/chat/send/                       Send a message (REST)
ChatMarkReadView        POST /api/chat/mark_read/<other_user_id>/  Mark messages as read
ChatInboxView           GET  /api/chat/inbox/                      All conversations + unread count
ChatUnreadCountView     GET  /api/chat/unread_count/               Total unread message count

Permission model
----------------
All endpoints: IsAuthenticated (all three roles may use chat).
Each user can only access their own messages — queries are always
filtered by request.user as sender or receiver.
"""

import logging

from django.db.models import Q, Max, Count
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ChatMessage
from .serializers import ChatMessageReadSerializer, ChatMessageSendSerializer
from apps.user.models import User

logger = logging.getLogger('apps')


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def ok(data=None, message='Success', code=200):
    return Response(
        {'success': True, 'code': code, 'message': message, 'data': data},
        status=code,
    )

def fail(message='Error', code=400, data=None):
    return Response(
        {'success': False, 'code': code, 'message': message, 'data': data},
        status=code,
    )


# ---------------------------------------------------------------------------
# Shared: all messages between two specific users (both directions)
# ---------------------------------------------------------------------------
def _conversation_qs(user_a_id, user_b_id):
    """
    Return all messages exchanged between user_a and user_b,
    in chronological order, with sender/receiver pre-fetched.
    """
    return (
        ChatMessage.objects
        .filter(
            Q(sender_id=user_a_id,   receiver_id=user_b_id) |
            Q(sender_id=user_b_id,   receiver_id=user_a_id)
        )
        .select_related('sender', 'receiver')
        .order_by('create_time')
    )


# ---------------------------------------------------------------------------
# 1. ChatHistoryView — GET /api/chat/history/<other_user_id>/
# ---------------------------------------------------------------------------
class ChatHistoryView(APIView):
    """
    GET /api/chat/history/<other_user_id>/

    Returns the full message history between the requesting user and the
    specified partner, ordered chronologically (oldest first).

    Called by the Vue frontend when the Chat tab is opened or when the
    user selects a conversation partner from the inbox.  New messages
    arriving after this call are delivered via WebSocket.

    Query parameters
    ----------------
    page / page_size    Paginate large histories (default: last 50 messages)

    Side effect
    -----------
    Marks all unread messages FROM the partner TO the requesting user as read.
    This mirrors the Vue frontend's expected behaviour when opening a chat.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, other_user_id):
        # Validate the partner exists
        partner = get_object_or_404(
            User.objects.filter(is_active=True), pk=other_user_id
        )

        qs = _conversation_qs(request.user.id, other_user_id)

        # ── Pagination ───────────────────────────────────────────────────
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(200, max(1, int(request.query_params.get('page_size', 50))))
        except (ValueError, TypeError):
            return fail('page and page_size must be integers.', code=400)

        total    = qs.count()
        offset   = (page - 1) * page_size
        messages = qs[offset: offset + page_size]

        # ── Mark received messages as read (side effect) ─────────────────
        unread_count = ChatMessage.objects.filter(
            sender_id   = other_user_id,
            receiver_id = request.user.id,
            is_read     = False,
        ).update(is_read=True)

        if unread_count:
            logger.debug(
                'ChatHistoryView: marked %d message(s) as read for user "%s" '
                'from partner id=%d.',
                unread_count, request.user.username, other_user_id,
            )

        serializer = ChatMessageReadSerializer(messages, many=True)
        return ok(
            data={
                'total':        total,
                'page':         page,
                'page_size':    page_size,
                'partner': {
                    'id':       partner.id,
                    'username': partner.username,
                    'name':     partner.name,
                    'role':     partner.role,
                },
                'results':      serializer.data,
            },
            message=f'{total} message(s) in this conversation.',
        )


# ---------------------------------------------------------------------------
# 2. ChatSendView — POST /api/chat/send/
# ---------------------------------------------------------------------------
class ChatSendView(APIView):
    """
    POST /api/chat/send/

    REST fallback for sending a message when WebSocket is unavailable.
    Under normal operation the Vue frontend sends messages via WebSocket;
    this endpoint is a reliable fallback (e.g. if the WS connection drops).

    Body: { "receiver_id": <int>, "content": "..." }

    The saved message is returned in the response so the frontend can
    append it to the chat panel optimistically without waiting for a
    WS echo.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChatMessageSendSerializer(
            data=request.data,
            context={'request': request},
        )
        if not serializer.is_valid():
            return fail('Validation failed.', code=400, data=serializer.errors)

        data = serializer.validated_data

        message = ChatMessage.objects.create(
            sender   = request.user,
            receiver = data['receiver'],
            content  = data['content'],
            is_read  = False,
        )

        logger.debug(
            'ChatSendView: user "%s" sent message id=%d to user "%s" via REST.',
            request.user.username, message.id, data['receiver'].username,
        )
        return ok(
            data=ChatMessageReadSerializer(
                ChatMessage.objects.select_related('sender', 'receiver').get(pk=message.pk)
            ).data,
            message='Message sent successfully.',
            code=201,
        )


# ---------------------------------------------------------------------------
# 3. ChatMarkReadView — POST /api/chat/mark_read/<other_user_id>/
# ---------------------------------------------------------------------------
class ChatMarkReadView(APIView):
    """
    POST /api/chat/mark_read/<other_user_id>/

    Marks all unread messages FROM <other_user_id> TO the requesting user
    as read.  Returns the count of messages marked.

    Called by the Vue frontend when:
    - The user opens a conversation (also done automatically in ChatHistoryView)
    - The user scrolls to the bottom of a conversation
    - The WebSocket read_receipt event is received
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, other_user_id):
        # Validate partner exists
        get_object_or_404(User, pk=other_user_id)

        marked_count = ChatMessage.objects.filter(
            sender_id   = other_user_id,
            receiver_id = request.user.id,
            is_read     = False,
        ).update(is_read=True)

        logger.debug(
            'ChatMarkReadView: %d message(s) marked as read for user "%s" '
            'from partner id=%d.',
            marked_count, request.user.username, other_user_id,
        )
        return ok(
            data={'marked_count': marked_count},
            message=(
                f'{marked_count} message(s) marked as read.'
                if marked_count else
                'No unread messages from this user.'
            ),
        )


# ---------------------------------------------------------------------------
# 4. ChatInboxView — GET /api/chat/inbox/
# ---------------------------------------------------------------------------
class ChatInboxView(APIView):
    """
    GET /api/chat/inbox/

    Returns a summary of all conversations the requesting user is part of,
    with the last message preview and unread count per conversation.

    Each inbox item:
    {
        "partner": { id, username, name, role },
        "last_message": { id, content, create_time, is_read, is_mine },
        "unread_count": <int>
    }

    Ordered by the most recent message (newest conversation first).

    Used to populate the conversation list panel in the Vue Chat tab
    (the left sidebar showing all chats).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        me = request.user

        # Find all unique conversation partners
        # (users who have sent to me OR received from me)
        sent_to     = ChatMessage.objects.filter(sender=me).values_list('receiver_id', flat=True).distinct()
        received_from = ChatMessage.objects.filter(receiver=me).values_list('sender_id', flat=True).distinct()
        partner_ids = set(list(sent_to) + list(received_from))

        inbox_items = []
        for partner_id in partner_ids:
            try:
                partner = User.objects.get(pk=partner_id, is_active=True)
            except User.DoesNotExist:
                continue

            # Last message in the conversation
            last_msg = (
                _conversation_qs(me.id, partner_id)
                .last()
            )
            if last_msg is None:
                continue

            # Unread count (messages FROM partner TO me that are unread)
            unread_count = ChatMessage.objects.filter(
                sender_id   = partner_id,
                receiver_id = me.id,
                is_read     = False,
            ).count()

            inbox_items.append({
                'partner': {
                    'id':       partner.id,
                    'username': partner.username,
                    'name':     partner.name,
                    'role':     partner.role,
                },
                'last_message': {
                    'id':          last_msg.id,
                    'content':     last_msg.content[:80],   # preview truncated
                    'create_time': last_msg.create_time.isoformat(),
                    'is_read':     last_msg.is_read,
                    'is_mine':     last_msg.sender_id == me.id,
                },
                'unread_count': unread_count,
            })

        # Sort by last message time (newest conversation first)
        inbox_items.sort(
            key=lambda x: x['last_message']['create_time'],
            reverse=True,
        )

        return ok(
            data={
                'total':   len(inbox_items),
                'results': inbox_items,
            },
            message=f'{len(inbox_items)} conversation(s) found.',
        )


# ---------------------------------------------------------------------------
# 5. ChatUnreadCountView — GET /api/chat/unread_count/
# ---------------------------------------------------------------------------
class ChatUnreadCountView(APIView):
    """
    GET /api/chat/unread_count/

    Returns the total number of unread messages for the requesting user
    across ALL conversations.

    Used to render the unread badge on the Chat nav button in the Vue
    header (e.g. "Chat (3)").

    Response: { "unread_count": <int> }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = ChatMessage.objects.filter(
            receiver = request.user,
            is_read  = False,
        ).count()

        return ok(
            data={'unread_count': count},
            message=f'{count} unread message(s).',
        )
