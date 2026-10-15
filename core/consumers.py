from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import asyncio
import json
import time
import logging

from .models import ParticipentCycle


logger = logging.getLogger(__name__)


class EchoConsumer(AsyncWebsocketConsumer):
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

        Sends a fresh data snapshot to this client only, every 5 seconds,
        starting 5 seconds after connect. Cancelled from disconnect().

        Sends both the flat, per-participant ranking (by power then
        voltage) and the per-cycle grouped totals, so the client can
        render either view without a second round trip.
        """
        try:
            while True:
                await asyncio.sleep(5)

                data = await self._build_payload()
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
    def _build_payload(self):
        # .only() trims the columns pulled off each joined table to just
        # what this payload uses, instead of loading full Participent/Cycle
        # rows every 5 seconds for every connected client.
        #
        # Ranked by power first, voltage as the tiebreaker, so ties on
        # power still resolve to a stable, meaningful order.
        allocations = (
            ParticipentCycle.objects
            .select_related('participent', 'cycle')
            .only(
                'voltage', 'amperage', 'power',
                'participent__id', 'participent__name', 'participent__profile',
                'cycle__cycle_no', 'cycle__controller_no'
            )
            .order_by('-power', '-voltage')
        )

        allocations = list(allocations)

        # Separate rank purely by voltage, independent of the power-based
        # 'rank' below, so the client can show either leaderboard.
        voltage_ranks = {
            allocation.pk: rank
            for rank, allocation in enumerate(
                sorted(allocations, key=lambda a: (a.voltage or 0.0), reverse=True),
                start=1,
            )
        }
        rows=[]
        for rank, allocation in enumerate(allocations, start=1):
            
            scaled = allocation.power * 10
            
            rows.append({
                'rank': rank,
                'voltage_rank': voltage_ranks[allocation.pk],
                'participent_id': allocation.participent.id,
                'controller_id' : allocation.cycle.controller_no,
                'participent': allocation.participent.name,
                'profile_image': self._build_absolute_uri(
                    self._profile_image_url(allocation.participent)
                ),
                'cycle': allocation.cycle.cycle_no,
                'voltage': allocation.voltage,
                'amperage': allocation.amperage,
                'power': scaled,
            })

        return {
            'type': 'heartbeat',
            'ts': time.time(),
            'allocations': rows,
        }
