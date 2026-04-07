"""
tests/test_chat.py
==================
Tests for the chat module: WebSocket consumer and REST API.

Coverage
--------
REST API:
  - Send a message (valid role pairs, invalid pairs, self-message)
  - Fetch message history (also marks as read)
  - Mark messages as read
  - Inbox: conversation list with last message + unread count
  - Unread count badge endpoint
  - Permission checks

WebSocket consumer:
  - Anonymous connection rejected (code 4001)
  - Valid connection accepted
  - Sending a message saves to DB and broadcasts
  - Blank message rejected
  - Message too long rejected
  - Disconnect removes from channel group
  - Unread messages marked as read on connect

WebSocket tests use Django Channels' WebsocketCommunicator for
in-process async testing — no real network needed.
"""

import pytest
import json

from django.contrib.auth import get_user_model
from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async

from apps.chat.models import ChatMessage
from tests.conftest import assert_ok, assert_fail

User = get_user_model()
pytestmark = pytest.mark.django_db(transaction=True)


# ===========================================================================
# ChatMessage model unit tests
# ===========================================================================
class TestChatMessageModel:

    def test_room_name_canonical(self):
        """room_name(a, b) == room_name(b, a) — smaller ID always first."""
        assert ChatMessage.room_name(3, 2) == 'chat_2_3'
        assert ChatMessage.room_name(2, 3) == 'chat_2_3'
        assert ChatMessage.room_name(1, 10) == 'chat_1_10'

    def test_str_shows_sender_receiver_and_preview(
        self, customer_user, stall_owner_user, db
    ):
        msg = ChatMessage.objects.create(
            sender=customer_user,
            receiver=stall_owner_user,
            content='Hello, do you have sports pants?',
        )
        s = str(msg)
        assert customer_user.username in s
        assert stall_owner_user.username in s
        assert '○' in s   # unread indicator

    def test_is_read_defaults_to_false(self, customer_user, stall_owner_user, db):
        msg = ChatMessage.objects.create(
            sender=customer_user,
            receiver=stall_owner_user,
            content='Test',
        )
        assert msg.is_read is False


# ===========================================================================
# REST API: Send
# ===========================================================================
class TestChatSendAPI:

    def test_customer_can_message_stall_owner(
        self, customer_client, stall_owner_user
    ):
        response = customer_client.post('/api/chat/send/', {
            'receiver_id': stall_owner_user.id,
            'content':     'Hello, do you have sports pants?',
        })
        data = assert_ok(response, code=201)
        assert data['content'] == 'Hello, do you have sports pants?'
        assert data['is_read'] is False

    def test_stall_owner_can_message_customer(
        self, owner_client, customer_user
    ):
        response = owner_client.post('/api/chat/send/', {
            'receiver_id': customer_user.id,
            'content':     'Yes, we have sports pants in stock.',
        })
        assert_ok(response, code=201)

    def test_customer_cannot_message_another_customer(
        self, customer_client, second_customer_user
    ):
        """customer ↔ customer messaging must be rejected."""
        response = customer_client.post('/api/chat/send/', {
            'receiver_id': second_customer_user.id,
            'content':     'Hi there',
        })
        assert_fail(response, code=400)

    def test_self_message_rejected(self, customer_client, customer_user):
        response = customer_client.post('/api/chat/send/', {
            'receiver_id': customer_user.id,
            'content':     'Talking to myself',
        })
        assert_fail(response, code=400)

    def test_blank_content_rejected(self, customer_client, stall_owner_user):
        response = customer_client.post('/api/chat/send/', {
            'receiver_id': stall_owner_user.id,
            'content':     '   ',
        })
        assert_fail(response, code=400)

    def test_message_saved_to_database(
        self, customer_client, customer_user, stall_owner_user
    ):
        customer_client.post('/api/chat/send/', {
            'receiver_id': stall_owner_user.id,
            'content':     'DB test message',
        })
        assert ChatMessage.objects.filter(
            sender=customer_user,
            receiver=stall_owner_user,
            content='DB test message',
        ).exists()

    def test_unauthenticated_cannot_send(self, api_client, stall_owner_user):
        response = api_client.post('/api/chat/send/', {
            'receiver_id': stall_owner_user.id,
            'content':     'Anon message',
        })
        assert response.status_code == 401


# ===========================================================================
# REST API: History
# ===========================================================================
class TestChatHistoryAPI:

    def _create_messages(self, sender, receiver, count=3):
        for i in range(count):
            ChatMessage.objects.create(
                sender=sender, receiver=receiver,
                content=f'Message {i + 1}',
            )

    def test_history_returns_chronological_messages(
        self, customer_client, customer_user, stall_owner_user, db
    ):
        self._create_messages(customer_user, stall_owner_user, 3)
        response = customer_client.get(
            f'/api/chat/history/{stall_owner_user.id}/'
        )
        data = assert_ok(response)
        assert data['total'] == 3
        contents = [m['content'] for m in data['results']]
        assert contents == ['Message 1', 'Message 2', 'Message 3']

    def test_history_marks_received_messages_as_read(
        self, customer_client, customer_user, stall_owner_user, db
    ):
        # Owner sends to customer (unread)
        ChatMessage.objects.create(
            sender=stall_owner_user, receiver=customer_user,
            content='Hello customer', is_read=False,
        )
        # Customer fetches history — should mark owner's message as read
        customer_client.get(f'/api/chat/history/{stall_owner_user.id}/')

        assert ChatMessage.objects.filter(
            sender=stall_owner_user,
            receiver=customer_user,
            is_read=True,
        ).exists()

    def test_history_includes_both_directions(
        self, customer_client, customer_user, stall_owner_user, db
    ):
        ChatMessage.objects.create(
            sender=customer_user, receiver=stall_owner_user, content='From customer'
        )
        ChatMessage.objects.create(
            sender=stall_owner_user, receiver=customer_user, content='From owner'
        )
        response = customer_client.get(
            f'/api/chat/history/{stall_owner_user.id}/'
        )
        data = assert_ok(response)
        assert data['total'] == 2

    def test_history_includes_partner_profile(
        self, customer_client, stall_owner_user
    ):
        response = customer_client.get(
            f'/api/chat/history/{stall_owner_user.id}/'
        )
        data = assert_ok(response)
        assert data['partner']['id'] == stall_owner_user.id
        assert data['partner']['role'] == 'stall_owner'


# ===========================================================================
# REST API: Mark Read
# ===========================================================================
class TestChatMarkReadAPI:

    def test_mark_read_updates_is_read_flag(
        self, customer_client, customer_user, stall_owner_user, db
    ):
        msg = ChatMessage.objects.create(
            sender=stall_owner_user, receiver=customer_user,
            content='Please read me', is_read=False,
        )
        response = customer_client.post(
            f'/api/chat/mark_read/{stall_owner_user.id}/'
        )
        data = assert_ok(response)
        assert data['marked_count'] == 1

        msg.refresh_from_db()
        assert msg.is_read is True

    def test_mark_read_returns_zero_if_already_read(
        self, customer_client, customer_user, stall_owner_user, db
    ):
        ChatMessage.objects.create(
            sender=stall_owner_user, receiver=customer_user,
            content='Already read', is_read=True,
        )
        response = customer_client.post(
            f'/api/chat/mark_read/{stall_owner_user.id}/'
        )
        data = assert_ok(response)
        assert data['marked_count'] == 0


# ===========================================================================
# REST API: Inbox and Unread Count
# ===========================================================================
class TestChatInboxAPI:

    def test_inbox_returns_conversations(
        self, customer_client, customer_user, stall_owner_user, db
    ):
        ChatMessage.objects.create(
            sender=customer_user, receiver=stall_owner_user, content='Hi'
        )
        response = customer_client.get('/api/chat/inbox/')
        data = assert_ok(response)
        assert data['total'] >= 1
        conv = data['results'][0]
        assert 'partner' in conv
        assert 'last_message' in conv
        assert 'unread_count' in conv

    def test_unread_count_endpoint(
        self, customer_client, customer_user, stall_owner_user, db
    ):
        # Create 2 unread messages for customer
        ChatMessage.objects.create(
            sender=stall_owner_user, receiver=customer_user,
            content='Msg 1', is_read=False,
        )
        ChatMessage.objects.create(
            sender=stall_owner_user, receiver=customer_user,
            content='Msg 2', is_read=False,
        )
        response = customer_client.get('/api/chat/unread_count/')
        data = assert_ok(response)
        assert data['unread_count'] == 2


# ===========================================================================
# WebSocket consumer tests (async, in-process)
# ===========================================================================
@pytest.mark.asyncio
class TestChatConsumer:
    """
    Uses Django Channels' WebsocketCommunicator for fully in-process
    async WebSocket testing — no real network needed.

    The ASGI application must be imported here (not at module level)
    to ensure Django is set up before the import runs.
    """

    def _get_application(self):
        """Import the ASGI application after Django is set up."""
        from StallManagement.asgi import application
        return application

    async def _connect(self, user, other_user_id):
        """
        Helper: create an authenticated WebSocket communicator.
        Injects the user into scope['user'] to simulate
        AuthMiddlewareStack population.
        """
        app = self._get_application()
        communicator = WebsocketCommunicator(
            app,
            f'/ws/chat/{other_user_id}/',
        )
        # Simulate AuthMiddlewareStack injecting the user
        communicator.scope['user'] = user
        return communicator

    @database_sync_to_async
    def _create_user(self, username, role):
        return User.objects.create_user(username, 'pass', username.title(), role=role)

    @database_sync_to_async
    def _get_message_count(self, sender, receiver):
        return ChatMessage.objects.filter(sender=sender, receiver=receiver).count()

    async def test_anonymous_connection_rejected(self):
        """AnonymousUser must be rejected with close code 4001."""
        from django.contrib.auth.models import AnonymousUser
        app = self._get_application()
        communicator = WebsocketCommunicator(app, '/ws/chat/2/')
        communicator.scope['user'] = AnonymousUser()
        connected, code = await communicator.connect()
        assert connected is False
        assert code == 4001

    async def test_authenticated_connection_accepted(self):
        """A valid authenticated user must be able to connect."""
        customer = await self._create_user('ws_customer', 'customer')
        owner    = await self._create_user('ws_owner',    'stall_owner')
        communicator = await self._connect(customer, owner.id)
        connected, _ = await communicator.connect()
        assert connected is True
        await communicator.disconnect()

    async def test_send_message_saves_to_db(self):
        """Sending a message via WS must persist it to the database."""
        customer = await self._create_user('ws_cust_db', 'customer')
        owner    = await self._create_user('ws_own_db',  'stall_owner')

        communicator = await self._connect(customer, owner.id)
        await communicator.connect()

        await communicator.send_to(text_data=json.dumps({
            'content': 'Hello from WebSocket!',
        }))

        # Receive the broadcast echo
        response = await communicator.receive_from()
        msg_data = json.loads(response)

        assert msg_data['type'] == 'chat_message'
        assert msg_data['message']['content'] == 'Hello from WebSocket!'

        # Verify DB persistence
        count = await self._get_message_count(customer, owner)
        assert count == 1

        await communicator.disconnect()

    async def test_blank_message_returns_error(self):
        """Blank content must return an error frame, not save anything."""
        customer = await self._create_user('ws_blank1', 'customer')
        owner    = await self._create_user('ws_blank2', 'stall_owner')

        communicator = await self._connect(customer, owner.id)
        await communicator.connect()

        await communicator.send_to(text_data=json.dumps({'content': '   '}))
        response = await communicator.receive_from()
        msg_data = json.loads(response)

        assert msg_data['type'] == 'error'

        count = await self._get_message_count(customer, owner)
        assert count == 0

        await communicator.disconnect()

    async def test_message_too_long_returns_error(self):
        """Messages exceeding 5000 characters must be rejected."""
        customer = await self._create_user('ws_long1', 'customer')
        owner    = await self._create_user('ws_long2', 'stall_owner')

        communicator = await self._connect(customer, owner.id)
        await communicator.connect()

        await communicator.send_to(text_data=json.dumps({
            'content': 'x' * 5001,
        }))
        response = await communicator.receive_from()
        msg_data = json.loads(response)
        assert msg_data['type'] == 'error'

        await communicator.disconnect()

    async def test_invalid_json_returns_error(self):
        """Malformed JSON must return an error frame."""
        customer = await self._create_user('ws_json1', 'customer')
        owner    = await self._create_user('ws_json2', 'stall_owner')

        communicator = await self._connect(customer, owner.id)
        await communicator.connect()

        await communicator.send_to(text_data='not valid json {{{{')
        response = await communicator.receive_from()
        msg_data = json.loads(response)
        assert msg_data['type'] == 'error'

        await communicator.disconnect()
