import asyncio
import struct
import minimalmodbus
import serial

from asgiref.sync import sync_to_async
from .services import save_monitor_data
from core.models import Cycle


import os
from pathlib import Path

def _load_env():
    # walk up from this file to find .env in the backend root
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        # fallback: one level up from current
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

_load_env()

PORT     = os.environ.get("DC_COM_PORT", "COM11")
BAUDRATE = int(os.environ.get("DC_BAUDRATE", "19200"))


POLL_INTERVAL = float(os.environ.get("DC_POLL", "1.0"))

DC_REG_VOLTAGE = 1606
DC_REG_CURRENT = 1608
DC_REG_POWER   = 1610
DC_REG_ENERGY  = 1612


@sync_to_async
def get_addresses():
    """
    Get controller numbers from Cycle table.
    Returns an empty list if no cycles are available.
    """
    return list(
        Cycle.objects.values_list("controller_no", flat=True)
    )


def make_instrument(addr):
    inst = minimalmodbus.Instrument(PORT, addr)

    inst.serial.baudrate = BAUDRATE
    inst.serial.bytesize = 8
    inst.serial.parity = serial.PARITY_NONE
    inst.serial.stopbits = 1
    inst.serial.timeout = 1.0

    inst.mode = minimalmodbus.MODE_RTU

    return inst


def to_float(regs):
    raw = struct.pack(
        ">I",
        (regs[0] << 16) | regs[1]
    )

    return struct.unpack(">f", raw)[0]


def read_one_sync(inst):
    """Blocking Modbus read — runs in a thread executor."""

    try:
        v_regs = inst.read_registers(
            DC_REG_VOLTAGE,
            2,
            functioncode=3
        )

        i_regs = inst.read_registers(
            DC_REG_CURRENT,
            2,
            functioncode=3
        )

        p_regs = inst.read_registers(
            DC_REG_POWER,
            2,
            functioncode=3
        )

        return {
            "voltage": round(to_float(v_regs), 2),
            "amperage": round(to_float(i_regs), 3),
            "power": round(to_float(p_regs), 3),
        }

    except Exception as e:
        print(f"[Modbus] Read error on instrument {inst.address}: {e}")
        return None


class ModbusPoller:

    def __init__(self):
        self.meters = {}

    async def update_meters(self):
        """
        Get the latest controller numbers from the database
        and create instruments for new controllers.
        """

        addresses = await get_addresses()

        # Convert all addresses to int upfront
        try:
            addresses = [int(addr) for addr in addresses]
        except (ValueError, TypeError) as e:
            print(f"[Modbus] Invalid controller_no value in DB: {e}")
            return

        # No controllers registered
        if not addresses:
            print("[Modbus] No controller addresses found in Cycle table.")
            self.meters = {}
            return

        # Add newly registered controllers
        for addr in addresses:

            if addr not in self.meters:
                try:
                    self.meters[addr] = make_instrument(addr)
                    print(f"[Modbus] Added controller: {addr}")

                except Exception as e:
                    print(f"[Modbus] Failed to create instrument for {addr}: {e}")

        # Remove controllers that no longer exist
        current_addresses = set(addresses)

        for addr in list(self.meters.keys()):

            if addr not in current_addresses:
                print(f"[Modbus] Removing controller: {addr}")
                del self.meters[addr]

    async def poll_forever(self):

        loop = asyncio.get_running_loop()

        while True:

            try:
                # Refresh controller addresses from DB (async-safe)
                await self.update_meters()

                # If no controllers are available, wait and retry
                if not self.meters:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # Poll each controller
                for addr, inst in list(self.meters.items()):

                    try:
                        reading = await loop.run_in_executor(
                            None,
                            read_one_sync,
                            inst
                        )

                        if reading is None:
                            continue

                        data = {
                            "controller_no": str(addr),
                            "voltage": reading["voltage"],
                            "amperage": reading["amperage"],
                            "power": reading["power"],
                        }

                        print(f"[Modbus] Read data: {data}")

                        await save_monitor_data(data)

                    except Exception as e:
                        print(f"[Modbus] Error polling controller {addr}: {e}")

                    # Small gap between meters
                    await asyncio.sleep(0.15)

            except asyncio.CancelledError:
                print("[Modbus] Poller cancelled, shutting down.")
                raise

            except Exception as e:
                print(f"[Modbus] Unexpected error in poll loop: {e}")

            await asyncio.sleep(POLL_INTERVAL)