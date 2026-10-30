"""The WebSocket a board opens to follow its production (see ``live.py``).

Browsers can't set headers on a WebSocket, and a token in the URL ends up in
logs, so the client sends ``{"type": "auth", "token": ...}`` as its first
message. Until then the socket hears nothing. Close codes: 4401 not signed in
(or signed out later), 4403 access lost, 4404 no such production or not on it.
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework.authtoken.models import Token

from . import live
from .access import role_for, visible_productions

NOT_SIGNED_IN, NO_ACCESS, NOT_FOUND = 4401, 4403, 4404


@database_sync_to_async
def user_for(token):
    found = Token.objects.select_related("user").filter(key=token).first()
    return found.user if found and found.user.is_active else None


@database_sync_to_async
def role_on(production_id, user):
    production = visible_productions(user).filter(pk=production_id).first()
    return role_for(production, user) if production else None


class ProductionConsumer(AsyncJsonWebsocketConsumer):
    user = None

    async def connect(self):
        self.production_id = self.scope["url_route"]["kwargs"]["production_id"]
        self.groups_joined = []
        await self.accept()

    async def disconnect(self, code):
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if self.user is not None:
            return  # Boards only listen; writes go through the REST API.
        if content.get("type") != "auth" or not isinstance(content.get("token"), str):
            await self.close(code=NOT_SIGNED_IN)
            return
        user = await user_for(content["token"])
        if user is None:
            await self.close(code=NOT_SIGNED_IN)
            return
        role = await role_on(self.production_id, user)
        if role is None:
            await self.close(code=NOT_FOUND)
            return
        self.user = user
        for group in (live.production_group(self.production_id), live.user_group(user.id)):
            await self.channel_layer.group_add(group, self.channel_name)
            self.groups_joined.append(group)
        await self.send_json({"type": "ready", "role": role})

    async def production_message(self, event):
        message = event["message"]
        if message["type"] == "access":
            role = await role_on(self.production_id, self.user)
            if role is None:
                await self.send_json({"type": "access.revoked"})
                await self.close(code=NO_ACCESS)
                return
        await self.send_json(message)
        if message["type"] == "production.deleted":
            await self.close(code=NOT_FOUND)

    async def session_ended(self, event):
        await self.send_json({"type": "session.ended"})
        await self.close(code=NOT_SIGNED_IN)
