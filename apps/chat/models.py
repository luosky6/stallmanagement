"""
apps/chat/models.py
===================
ChatMessage model — maps to the `chat_messages` table in db_market.sql.

Role in the system
------------------
Supports real-time direct messaging between a customer and a stall owner.
The Vue frontend's Chat tab shows a conversation thread between the current
user (customer or stall_owner) and the other party.

The frontend's simulated auto-reply:
    this.messages.push({ from: 'Stall Owner', text: 'Thanks...' })
is replaced in the backend by a genuine WebSocket consumer (consumers.py)
that broadcasts the new message to all participants in the room.

Room naming convention
----------------------
The WebSocket room name is derived from the two participant user IDs:
    room = f"chat_{min(sender_id, receiver_id)}_{max(sender_id, receiver_id)}"
This ensures both parties always join the same channel group regardless
of who initiated the connection, and makes it easy to query all messages
in a conversation using the same two IDs.

Message flow
------------
1.  Client sends WS message → ChatConsumer.receive()
2.  Consumer saves ChatMessage to DB
3.  Consumer broadcasts to the channel group (both users' WS connections)
4.  Each client's ChatConsumer.send() pushes the message to the browser
5.  REST endpoint GET /api/chat/history/<user_id>/ loads prior messages
    on page load / tab open (before the WS connection delivers new ones)

Database table: `chat_messages`  (matches db_market.sql exactly)

SQL reference:
    CREATE TABLE `chat_messages` (
      `id`          INT AUTO_INCREMENT PRIMARY KEY,
      `sender_id`   INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      `receiver_id` INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      `content`     TEXT NOT NULL,
      `is_read`     TINYINT(1) DEFAULT 0,
      `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP
    )
"""

from django.conf import settings
from django.db import models

from apps.common.mixins import TimeStampMixin


class ChatMessage(TimeStampMixin):
    """
    A single chat message between two users.

    Inherits from TimeStampMixin:
        create_time  →  auto-set when the message is saved (sent time)
        modify_time  →  auto-updated on every save (used when is_read changes)

    Messages are immutable once sent (content cannot be edited).
    The only mutable field after creation is is_read.
    """

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='sent_messages',
        verbose_name='Sender',
        help_text='The user who sent this message.',
        db_column='sender_id',
    )

    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='received_messages',
        verbose_name='Receiver',
        help_text='The user who should receive this message.',
        db_column='receiver_id',
    )

    content = models.TextField(
        verbose_name='Message Content',
        help_text='The text body of the message.',
    )

    is_read = models.BooleanField(
        default=False,
        verbose_name='Read',
        help_text='True when the receiver has read this message.',
    )

    # create_time → inherited from TimeStampMixin (= sent time)
    # modify_time → inherited from TimeStampMixin (updated when is_read changes)

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        app_label = 'chat'
        db_table            = 'chat_messages'
        verbose_name        = 'Chat Message'
        verbose_name_plural = 'Chat Messages'
        ordering            = ['create_time']   # chronological for chat display
        indexes = [
            # Speed up conversation history queries (both directions)
            models.Index(
                fields=['sender', 'receiver'],
                name='idx_chat_sender_receiver',
            ),
            models.Index(
                fields=['receiver', 'sender'],
                name='idx_chat_receiver_sender',
            ),
            # Speed up unread count queries
            models.Index(
                fields=['receiver', 'is_read'],
                name='idx_chat_receiver_read',
            ),
            models.Index(
                fields=['create_time'],
                name='idx_chat_created',
            ),
        ]

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        read_label = '✓' if self.is_read else '○'
        return (
            f'{read_label} {self.sender.username} → '
            f'{self.receiver.username}: '
            f'{self.content[:40]}{"..." if len(self.content) > 40 else ""}'
        )

    # ------------------------------------------------------------------
    # Helper: derive the room name from two user IDs
    # ------------------------------------------------------------------
    @staticmethod
    def room_name(user_id_a: int, user_id_b: int) -> str:
        """
        Generate the canonical WebSocket room name for two users.
        The smaller ID always comes first so both users join the same group.

        Example: room_name(3, 2) == room_name(2, 3) == 'chat_2_3'
        """
        lo, hi = sorted([user_id_a, user_id_b])
        return f'chat_{lo}_{hi}'
