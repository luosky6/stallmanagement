"""
apps/chat/serializers.py
========================
DRF serializers for the ChatMessage model.

Serializers
-----------
ChatMessageReadSerializer
    Full read-only message representation returned by the history endpoint.
    Includes nested sender and receiver summaries (id, username, name)
    so the Vue chat panel can render "from" labels and avatar initials.

ChatMessageSendSerializer
    Write serializer for the REST send endpoint (POST /api/chat/send/).
    Validates receiver_id, rejects self-messages, and enforces that the
    two participants have a valid stall_owner ↔ customer relationship
    (a customer may not message another customer, etc.).

ChatMessageWebSocketSerializer
    Lightweight serializer used by the WebSocket consumer (consumers.py)
    to serialise a message before broadcasting it to the channel group.
    Uses only JSON-safe primitives (no DRF Response — the consumer calls
    .data directly and passes it to async_to_sync / channel_layer.send).
"""

from rest_framework import serializers

from .models import ChatMessage
from apps.user.models import User


# ---------------------------------------------------------------------------
# Nested user summary — embedded in read responses
# ---------------------------------------------------------------------------
class ChatUserSummarySerializer(serializers.ModelSerializer):
    """Compact user profile embedded in every message response."""

    class Meta:
        model  = User
        fields = ['id', 'username', 'name', 'role']
        read_only_fields = fields


# ---------------------------------------------------------------------------
# 1. ChatMessageReadSerializer — full read output (REST history)
# ---------------------------------------------------------------------------
class ChatMessageReadSerializer(serializers.ModelSerializer):
    """
    Read-only representation returned by:
        GET /api/chat/history/<other_user_id>/
        GET /api/chat/inbox/
    """

    sender   = ChatUserSummarySerializer(read_only=True)
    receiver = ChatUserSummarySerializer(read_only=True)

    class Meta:
        model  = ChatMessage
        fields = [
            'id',
            'sender',
            'receiver',
            'content',
            'is_read',
            'create_time',
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# 2. ChatMessageSendSerializer — REST send endpoint
# ---------------------------------------------------------------------------
class ChatMessageSendSerializer(serializers.Serializer):
    """
    Write serializer for POST /api/chat/send/.

    The sender is always request.user — never supplied in the body.

    Validation rules
    ----------------
    receiver_id
        Must reference an existing, active user.
        Cannot be the same as the sender (no self-messages).

    content
        Required. Stripped. Cannot be blank.

    Role pairing rules
    ------------------
    Valid pairs:
        customer    ↔  stall_owner  (the primary use case)
        stall_owner ↔  customer
        admin       ↔  anyone       (admin can contact any user)

    Invalid pairs (rejected):
        customer    ↔  customer     (customers cannot message each other)
        stall_owner ↔  stall_owner  (stall owners cannot message each other)
    """

    receiver_id = serializers.IntegerField(
        help_text='ID of the user to send the message to.',
    )
    content = serializers.CharField(
        max_length=5000,
        help_text='Message text body.',
    )

    def validate_receiver_id(self, value):
        """Validate receiver exists and is active."""
        try:
            receiver = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                f'User with id={value} does not exist.'
            )
        if not receiver.is_active:
            raise serializers.ValidationError(
                f'Cannot send a message to deactivated user "{receiver.username}".'
            )
        return value

    def validate_content(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Message content cannot be blank.')
        return value

    def validate(self, attrs):
        request     = self.context.get('request')
        sender      = request.user
        receiver_id = attrs['receiver_id']

        # Self-message guard
        if sender.id == receiver_id:
            raise serializers.ValidationError(
                {'receiver_id': 'You cannot send a message to yourself.'}
            )

        receiver = User.objects.get(pk=receiver_id)

        # Role pairing guard
        sender_role   = sender.role
        receiver_role = receiver.role

        invalid_pairs = {
            (User.Role.CUSTOMER,    User.Role.CUSTOMER),
            (User.Role.STALL_OWNER, User.Role.STALL_OWNER),
        }
        if (sender_role, receiver_role) in invalid_pairs:
            raise serializers.ValidationError({
                'receiver_id': (
                    f'A {sender_role} cannot send messages to another {receiver_role}. '
                    'Chat is between customers and stall owners only.'
                )
            })

        # Attach the resolved receiver object so the view doesn't re-query
        attrs['receiver'] = receiver
        return attrs


# ---------------------------------------------------------------------------
# 3. ChatMessageWebSocketSerializer — WebSocket broadcast payload
# ---------------------------------------------------------------------------
class ChatMessageWebSocketSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for WebSocket message broadcast.

    Used by ChatConsumer to convert a saved ChatMessage into a JSON-safe
    dict that is sent over the channel layer to all group members.

    Includes sender summary (id, username, name) so the Vue chat panel can
    display the sender's name and determine message alignment (left/right)
    without an extra HTTP request.
    """

    sender_id       = serializers.IntegerField(source='sender.id',       read_only=True)
    sender_username = serializers.CharField(source='sender.username',    read_only=True)
    sender_name     = serializers.CharField(source='sender.name',        read_only=True)
    receiver_id     = serializers.IntegerField(source='receiver.id',     read_only=True)

    class Meta:
        model  = ChatMessage
        fields = [
            'id',
            'sender_id',
            'sender_username',
            'sender_name',
            'receiver_id',
            'content',
            'is_read',
            'create_time',
        ]
        read_only_fields = fields
