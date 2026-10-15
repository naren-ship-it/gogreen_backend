from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import json


GROUP_NAME = "app_title"


class AppTitleConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        # Get role from URL
        self.role = self.scope["url_route"]["kwargs"].get("role")

        # Only allow admin or client
        if self.role not in ["admin", "client"]:
            await self.close()
            return

        await self.channel_layer.group_add(
            GROUP_NAME,
            self.channel_name,
        )

        await self.accept()

        # Send current title to both admin and client
        title = await self.get_title()

        await self.send(
            text_data=json.dumps({
                "type": "title_updated",
                "title": title,
            })
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            GROUP_NAME,
            self.channel_name,
        )

    async def receive(self, text_data):
        # Only ADMIN can send/update data
        if self.role != "admin":
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        if data.get("type") != "update_title":
            return

        title = data.get("title", "").strip()

        if not title:
            return

        # Save title
        await self.save_title(title)

        # Broadcast to everyone
        await self.channel_layer.group_send(
            GROUP_NAME,
            {
                "type": "title_update",
                "title": title,
            },
        )

    async def title_update(self, event):
        await self.send(
            text_data=json.dumps({
                "type": "title_updated",
                "title": event["title"],
            })
        )

    @database_sync_to_async
    def get_title(self):
        from core.models import AppTitle

        obj = AppTitle.objects.last()

        return obj.title if obj else "Go Green"

    @database_sync_to_async
    def save_title(self, title):
        from core.models import AppTitle

        obj = AppTitle.objects.last()

        if obj:
            obj.title = title
            obj.save()
        else:
            AppTitle.objects.create(title=title)