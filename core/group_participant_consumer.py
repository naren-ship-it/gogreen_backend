from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import asyncio
import json
import time
import logging

from .models import Group

logger = logging.getLogger(__name__)


class GroupRankingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

        # Kick off this connection's own 5-second send loop. Each client
        # gets an independent timer starting the moment it connects, rather
        # than a schedule shared across all clients.
        self.send_loop_task = asyncio.ensure_future(self._send_every_5_seconds())

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is not None:
            await self.send(text_data=f"ECHO: {text_data}")
        elif bytes_data is not None:
            await self.send(bytes_data=bytes_data)

    async def disconnect(self, close_code):
        # Stop this connection's loop first so it can't fire against a
        # socket that's already going away.
        task = getattr(self, 'send_loop_task', None)
        if task is not None:
            task.cancel()

    async def _send_every_5_seconds(self):
        """Runs for the lifetime of this connection.

        Sends a fresh group-ranking snapshot to this client only, every
        5 seconds, starting 5 seconds after connect. Cancelled from
        disconnect().
        """
        try:
            while True:
                await asyncio.sleep(5)

                data = await self._build_group_ranking_payload()
                await self.send(text_data=json.dumps(data))
        except asyncio.CancelledError:
            # Normal shutdown path when the client disconnects.
            raise
        except Exception as exc:
            logger.exception('Per-connection 5s send loop failed: %s', exc)

    @staticmethod
    def _profile_image_url(participent):
        """Return the participant's profile image path, or None.

        `profile` is blank/null-able, and calling .url on an empty
        ImageFieldFile raises ValueError — this keeps that off the hot path
        of every heartbeat tick.
        """
        if not participent.profile:
            return None
        try:
            return participent.profile.url
        except ValueError:
            return None

    def _build_absolute_uri(self, path):
        """Turn a MEDIA_URL-relative path (e.g. /media/x.jpg) into a full
        URL using this connection's own scope, since a consumer has no HTTP
        request to build one from the way a view does.
        """
        if not path:
            return None

        scheme = 'https' if self.scope.get('scheme') == 'wss' else 'http'

        headers = dict(self.scope.get('headers') or [])
        host_header = headers.get(b'host')
        if host_header:
            host = host_header.decode('latin-1')
        else:
            server_host, server_port = self.scope.get('server') or (None, None)
            host = server_host or 'localhost'
            if server_port:
                host = f'{host}:{server_port}'

        return f'{scheme}://{host}{path}'

    @database_sync_to_async
    def _build_group_ranking_payload(self):
        # select_related on member -> participent/cycle avoids N+1 queries
        # while walking each group's members below; prefetch_related pulls
        # the whole members set for each group in one extra query.
        groups = (
            Group.objects
            .prefetch_related(
                'members__participent',
                'members__cycle',
            )
        )

        group_rows = []
        for group in groups:
            members = group.members.all()

            total_power = 0.0
            total_voltage = 0.0
            total_amperage = 0.0
            participants = []

            for member in members:
                power = member.power or 0.0
                voltage = member.voltage or 0.0
                amperage = member.amperage or 0.0

                total_power += power
                total_voltage += voltage
                total_amperage += amperage

                participants.append({
                    'id': member.id,
                    'name': member.participent.name,
                    'profile_image': self._build_absolute_uri(
                        self._profile_image_url(member.participent)
                    ),
                    'cycle': member.cycle.cycle_no,
                    'controller_no': member.cycle.controller_no,
                    'voltage': voltage,
                    'amperage': amperage,
                    'power': power,
                })

            # Highest power participant leads the group's member listing.
            participants.sort(key=lambda p: p['power'], reverse=True)

            group_rows.append({
                'group_id': group.id,
                'group_name': group.name,
                'member_count': len(participants),
                'total_power': total_power,
                'total_voltage': total_voltage,
                'total_amperage': total_amperage,
                'participants': participants,
            })

        # Rank groups by total power, highest first. Groups with zero
        # members still show up (rank included) so the UI doesn't have to
        # special-case an empty group disappearing from the board.
        group_rows.sort(key=lambda g: g['total_power'], reverse=True)
        for rank, row in enumerate(group_rows, start=1):
            row['rank'] = rank

        return {
            'type': 'group_heartbeat',
            'ts': time.time(),
            'groups': group_rows,
        }