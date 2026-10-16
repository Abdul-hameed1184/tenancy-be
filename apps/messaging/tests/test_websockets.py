"""
WebSocket behaviour through the real ASGI stack: OriginValidator -> TicketAuthMiddleware ->
URLRouter -> ThreadConsumer, with the in-memory channel layer.

transaction=True: async consumers run their DB work in worker threads with their own
connections, so data must really be committed for them to see it.
"""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from apps.accounts import realtime, services
from apps.messaging import services as messaging_services
from apps.messaging.models import Message, ThreadParticipant
from config.asgi import application
from tests.factories import ThreadFactory, UserFactory

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

ORIGIN = (b"origin", b"http://localhost:5173")


def _ticket_for(user) -> str:
    issued = services.start_session(user)
    user.auth_session_id = issued.session.id
    return realtime.issue_ticket(user)


def _two_tenants_in_a_thread():
    a, b = UserFactory(role="tenant"), UserFactory(role="tenant")
    return a, b, ThreadFactory(members=[a, b])


async def connect(thread_id, ticket=None, origin=ORIGIN):
    path = f"/ws/threads/{thread_id}/" + (f"?ticket={ticket}" if ticket else "")
    communicator = WebsocketCommunicator(application, path, headers=[origin] if origin else [])
    connected, code = await communicator.connect()
    return communicator, connected, code


async def test_anonymous_connection_is_refused():
    _, _, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    _, connected, code = await connect(thread.id)
    assert not connected and code == 4401


async def test_invalid_ticket_is_refused():
    _, _, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    _, connected, code = await connect(thread.id, ticket="forged-ticket")
    assert not connected and code == 4401


async def test_non_participant_is_refused():
    _, _, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    outsider = await database_sync_to_async(UserFactory)()
    ticket = await database_sync_to_async(_ticket_for)(outsider)
    _, connected, code = await connect(thread.id, ticket)
    assert not connected and code == 4403


async def test_foreign_origin_is_refused():
    a, _, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    ticket = await database_sync_to_async(_ticket_for)(a)
    _, connected, _ = await connect(thread.id, ticket, origin=(b"origin", b"https://evil.example"))
    assert not connected


async def test_ticket_is_single_use():
    a, _, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    ticket = await database_sync_to_async(_ticket_for)(a)
    first, connected, _ = await connect(thread.id, ticket)
    assert connected
    _, reconnected, code = await connect(thread.id, ticket)
    assert not reconnected and code == 4401
    await first.disconnect()


async def test_message_from_a_reaches_b_and_is_persisted():
    a, b, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    ws_a, ok_a, _ = await connect(thread.id, await database_sync_to_async(_ticket_for)(a))
    ws_b, ok_b, _ = await connect(thread.id, await database_sync_to_async(_ticket_for)(b))
    assert ok_a and ok_b

    await ws_a.send_json_to({"type": "message.send", "body": "Is the viewing still on?"})

    received_by_b = await ws_b.receive_json_from(timeout=3)
    echoed_to_a = await ws_a.receive_json_from(timeout=3)
    assert received_by_b["type"] == "message.created"
    assert received_by_b["message"]["body"] == "Is the viewing still on?"
    assert received_by_b["message"]["senderId"] == str(a.id)
    assert echoed_to_a["message"]["id"] == received_by_b["message"]["id"]
    assert await database_sync_to_async(Message.objects.filter(thread=thread).count)() == 1

    await ws_a.disconnect()
    await ws_b.disconnect()


async def test_message_sent_over_rest_is_pushed_to_open_sockets():
    a, b, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    ws_b, ok, _ = await connect(thread.id, await database_sync_to_async(_ticket_for)(b))
    assert ok

    await database_sync_to_async(messaging_services.send_message)(
        thread_id=thread.id, sender=a, body="Sent via REST"
    )

    pushed = await ws_b.receive_json_from(timeout=3)
    assert pushed["message"]["body"] == "Sent via REST"
    await ws_b.disconnect()


async def test_invalid_payload_gets_error_frame_and_nothing_is_saved():
    a, _, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    ws, ok, _ = await connect(thread.id, await database_sync_to_async(_ticket_for)(a))
    assert ok
    await ws.send_json_to({"type": "message.send", "body": "   "})
    assert (await ws.receive_json_from(timeout=3))["type"] == "error"
    await ws.send_json_to({"type": "delete.everything"})
    assert (await ws.receive_json_from(timeout=3))["type"] == "error"
    assert await database_sync_to_async(Message.objects.count)() == 0
    await ws.disconnect()


async def test_participant_removed_mid_session_cannot_keep_posting():
    a, _, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    ws, ok, _ = await connect(thread.id, await database_sync_to_async(_ticket_for)(a))
    assert ok
    await database_sync_to_async(ThreadParticipant.objects.filter(thread=thread, user=a).delete)()

    await ws.send_json_to({"type": "message.send", "body": "still here?"})

    assert (await ws.receive_json_from(timeout=3))["type"] == "error"
    assert (await ws.receive_output(timeout=3))["type"] == "websocket.close"
    assert await database_sync_to_async(Message.objects.count)() == 0


async def test_disconnect_leaves_the_group_cleanly():
    a, b, thread = await database_sync_to_async(_two_tenants_in_a_thread)()
    ws_a, _, _ = await connect(thread.id, await database_sync_to_async(_ticket_for)(a))
    ws_b, _, _ = await connect(thread.id, await database_sync_to_async(_ticket_for)(b))
    await ws_b.disconnect()

    await ws_a.send_json_to({"type": "message.send", "body": "anyone?"})
    assert (await ws_a.receive_json_from(timeout=3))["message"]["body"] == "anyone?"
    assert await ws_b.receive_nothing(timeout=0.3)
    await ws_a.disconnect()
