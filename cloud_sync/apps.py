import asyncio

from .sync.modbus_client import ModbusPoller


def start():
    poller = ModbusPoller()
    asyncio.run(poller.poll_forever())