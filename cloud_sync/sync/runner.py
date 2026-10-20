import asyncio

from .modbus_client import CloudSocketClient


def start():

    client = CloudSocketClient()

    asyncio.run(client.connect())