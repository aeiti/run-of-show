"""Live updates over WebSockets: who can listen, and what they hear."""

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework.authtoken.models import Token

from config.asgi import application
from shows.models import Membership
from shows.tests import client_for

ORIGIN = (b"origin", b"http://localhost:3200")
pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def allowed_origins(monkeypatch):
    # The validator copied CORS_ALLOWED_ORIGINS when asgi.py was imported, so a
    # settings override can't reach it, and a local .env may list other origins.
    monkeypatch.setattr(application.application_mapping["websocket"], "allowed_origins", [ORIGIN[1].decode()])


@sync_to_async
def token_for(user):
    return Token.objects.get_or_create(user=user)[0].key


@sync_to_async
def call(user, method, url, body=None):
    response = getattr(client_for(user), method)(url, body or {}, format="json")
    return response.status_code


async def connect(production, token, origin=ORIGIN):
    socket = WebsocketCommunicator(application, f"/ws/productions/{production.id}/", headers=[origin])
    connected, _ = await socket.connect()
    assert connected
    await socket.send_json_to({"type": "auth", "token": token})
    return socket


async def closed_with(socket):
    output = await socket.receive_output(timeout=1)
    assert output["type"] == "websocket.close", output
    return output.get("code")


async def test_board_hears_operator_actions_with_the_new_state(show):
    socket = await connect(show.production, await token_for(show.owner))
    assert await socket.receive_json_from() == {"type": "ready", "role": "owner"}

    assert await call(show.owner, "post", f"/api/runs/{show.run.id}/go/") == 201
    message = await socket.receive_json_from()
    assert (message["type"], message["run"]) == ("run.event", show.run.id)
    assert message["event"]["action"] == "go" and message["event"]["cue_number"] == "1"
    assert message["state"]["active_number"] == "1"
    await socket.disconnect()


async def test_each_kind_of_change_is_announced(show):
    socket = await connect(show.production, await token_for(show.owner))
    await socket.receive_json_from()
    prod, cue, run = show.production, show.cues["1"], show.run

    await call(show.owner, "patch", f"/api/cues/{cue.id}/", {"label": "New"})
    assert await socket.receive_json_from() == {"type": "cues"}
    await call(show.owner, "post", f"/api/productions/{prod.id}/runs/", {"label": "Run 2"})
    assert await socket.receive_json_from() == {"type": "runs"}
    await call(show.owner, "post", f"/api/runs/{run.id}/notes/", {"cue": cue.id, "text": "late"})
    assert await socket.receive_json_from() == {"type": "notes", "run": run.id}
    await call(show.owner, "patch", f"/api/productions/{prod.id}/", {"venue": "Hall"})
    assert await socket.receive_json_from() == {"type": "production"}
    # Reads and refused writes say nothing.
    await call(show.owner, "get", f"/api/productions/{prod.id}/cues/")
    await call(show.owner, "post", f"/api/productions/{prod.id}/cues/", {"number": "1"})
    await call(show.owner, "post", f"/api/productions/{prod.id}/cues/import/", {"text": "number\n7"})  # dry run
    assert await socket.receive_nothing(timeout=0.2)
    await socket.disconnect()


async def test_socket_needs_a_valid_token_first(show):
    socket = await connect(show.production, "not-a-token")
    assert await closed_with(socket) == 4401

    socket = WebsocketCommunicator(application, f"/ws/productions/{show.production.id}/", headers=[ORIGIN])
    await socket.connect()
    await socket.send_json_to({"type": "subscribe"})
    assert await closed_with(socket) == 4401


async def test_strangers_and_other_origins_are_refused(show, make_user):
    stranger = await sync_to_async(make_user)("mallory")
    socket = await connect(show.production, await token_for(stranger))
    assert await closed_with(socket) == 4404

    elsewhere = WebsocketCommunicator(
        application, f"/ws/productions/{show.production.id}/", headers=[(b"origin", b"https://evil.example")]
    )
    connected, _ = await elsewhere.connect()
    assert not connected


async def test_removed_member_is_cut_off_and_others_hear_about_it(show, make_user):
    bob = await sync_to_async(make_user)("bob")
    membership = await sync_to_async(Membership.objects.create)(production=show.production, user=bob, role="viewer")
    bob_socket = await connect(show.production, await token_for(bob))
    assert (await bob_socket.receive_json_from())["role"] == "viewer"
    owner_socket = await connect(show.production, await token_for(show.owner))
    await owner_socket.receive_json_from()

    assert await call(show.owner, "delete", f"/api/memberships/{membership.id}/") == 204
    assert await bob_socket.receive_json_from() == {"type": "access.revoked"}
    assert await closed_with(bob_socket) == 4403
    assert await owner_socket.receive_json_from() == {"type": "access"}
    await owner_socket.disconnect()


async def test_signing_out_or_suspension_closes_the_users_sockets(show, make_user):
    socket = await connect(show.production, await token_for(show.owner))
    await socket.receive_json_from()
    assert await call(show.owner, "post", "/api/auth/logout/") == 204
    assert await socket.receive_json_from() == {"type": "session.ended"}
    assert await closed_with(socket) == 4401

    bob = await sync_to_async(make_user)("bob")
    await sync_to_async(Membership.objects.create)(production=show.production, user=bob, role="operator")
    admin = await sync_to_async(make_user)("root")
    admin.is_staff = True
    await sync_to_async(admin.save)()
    socket = await connect(show.production, await token_for(bob))
    await socket.receive_json_from()
    assert await call(admin, "patch", f"/api/admin/users/{bob.id}/", {"is_active": False}) == 200
    assert await socket.receive_json_from() == {"type": "session.ended"}
    assert await closed_with(socket) == 4401


async def test_deleting_the_production_sends_boards_away(show):
    socket = await connect(show.production, await token_for(show.owner))
    await socket.receive_json_from()
    assert await call(show.owner, "delete", f"/api/productions/{show.production.id}/") == 204
    assert await socket.receive_json_from() == {"type": "production.deleted"}
    assert await closed_with(socket) == 4404


@sync_to_async
def upload(user, url, method="post", **fields):
    from django.core.files.uploadedfile import SimpleUploadedFile

    files = {k: SimpleUploadedFile(*v) if isinstance(v, tuple) else v for k, v in fields.items()}
    return getattr(client_for(user), method)(url, files, format="multipart")


async def test_file_and_logo_changes_are_announced(show, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    socket = await connect(show.production, await token_for(show.owner))
    await socket.receive_json_from()
    prod = show.production

    added = await upload(show.owner, f"/api/productions/{prod.id}/files/", file=("plan.txt", b"plan"), kind="other")
    assert added.status_code == 201
    assert await socket.receive_json_from() == {"type": "files"}
    assert await call(show.owner, "delete", f"/api/files/{added.data['id']}/") == 204
    assert await socket.receive_json_from() == {"type": "files"}

    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
    logo = await upload(show.owner, f"/api/productions/{prod.id}/logo/", method="put", file=("logo.png", png))
    assert logo.status_code == 200
    assert await socket.receive_json_from() == {"type": "production"}
    # Listing files and fetching the logo say nothing.
    await call(show.owner, "get", f"/api/productions/{prod.id}/files/")
    await call(show.owner, "get", f"/api/productions/{prod.id}/logo/")
    assert await socket.receive_nothing(timeout=0.2)
    await socket.disconnect()
