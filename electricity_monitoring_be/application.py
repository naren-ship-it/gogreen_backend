import asyncio
import traceback

from electricity_monitoring_be.asgi import application as django_application


class LifespanApplication:

    def __init__(self, app):
        self.app = app
        self.task = None

    def _on_poller_done(self, task):
        """Callback to surface silent crashes in the poller task."""
        if task.cancelled():
            print("[Lifespan] ModbusPoller task was cancelled.")
            return

        exc = task.exception()

        if exc:
            print(f"[Lifespan] ModbusPoller crashed with: {exc}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)

    async def __call__(self, scope, receive, send):

        if scope["type"] == "lifespan":

            while True:
                message = await receive()

                if message["type"] == "lifespan.startup":
                    print("[Lifespan] Starting Modbus Poller...")

                    try:
                        from cloud_sync.sync.modbus_client import ModbusPoller

                        self.task = asyncio.create_task(
                            ModbusPoller().poll_forever()
                        )

                        # Surfaces any silent crash in the background task
                        self.task.add_done_callback(self._on_poller_done)

                        print("[Lifespan] Modbus Poller started successfully.")

                    except Exception as e:
                        print(f"[Lifespan] Failed to start Modbus Poller: {e}")
                        traceback.print_exc()

                    await send({"type": "lifespan.startup.complete"})

                elif message["type"] == "lifespan.shutdown":
                    print("[Lifespan] Shutting down Modbus Poller...")

                    if self.task and not self.task.done():
                        self.task.cancel()

                        try:
                            await self.task
                        except asyncio.CancelledError:
                            print("[Lifespan] Modbus Poller stopped cleanly.")

                    await send({"type": "lifespan.shutdown.complete"})
                    return

        else:
            await self.app(scope, receive, send)


application = LifespanApplication(django_application)