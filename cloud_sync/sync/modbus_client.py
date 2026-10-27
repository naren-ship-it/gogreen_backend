import asyncio
import struct
import minimalmodbus
import serial
import os

from pathlib import Path
from asgiref.sync import sync_to_async

from .services import save_monitor_data
from core.models import Cycle
from core.models import DCModbusReadControl as ModbusReadControl



# ==================================================
# ENVIRONMENT CONFIGURATION
# ==================================================

def _load_env():
    """
    Load .env from the backend root directory.
    """

    env_path = Path(__file__).resolve().parents[3] / ".env"

    if not env_path.exists():
        env_path = (
            Path(__file__).resolve().parent.parent.parent / ".env"
        )

    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:

            for line in f:
                line = line.strip()

                if line and "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


_load_env()


# ==================================================
# MODBUS CONFIGURATION
# ==================================================

PORT = os.environ.get("DC_COM_PORT", "COM11")

BAUDRATE = int(
    os.environ.get("DC_BAUDRATE", "19200")
)

POLL_INTERVAL = float(
    os.environ.get("DC_POLL", "1.0")
)

DC_REG_VOLTAGE = 1606
DC_REG_CURRENT = 1608
DC_REG_POWER = 1610
DC_REG_ENERGY = 1612


# ==================================================
# DATABASE FUNCTIONS
# ==================================================

@sync_to_async
def get_addresses():
    """
    Get controller numbers from the Cycle table.
    """

    return list(
        Cycle.objects.values_list(
            "controller_no",
            flat=True
        )
    )


@sync_to_async
def is_read_enabled():
    """
    Check whether the backend Read Data switch is ON.
    """

    control = ModbusReadControl.get_control()

    return control.read_enabled


# ==================================================
# SERIAL PORT CONFIGURATION
# ==================================================

def create_serial_port():
    """
    Create a serial connection object without opening
    the COM port.

    The port will be opened only when Read Data is ON.
    """

    ser = serial.Serial(
        port=None,
        baudrate=BAUDRATE,
        bytesize=8,
        parity=serial.PARITY_NONE,
        stopbits=1,
        timeout=1.0,
    )

    ser.port = PORT

    return ser


# ==================================================
# CREATE MODBUS INSTRUMENT
# ==================================================

def make_instrument(addr, shared_serial):
    """
    Create a Modbus instrument using the shared COM port.
    """

    inst = minimalmodbus.Instrument(
        PORT,
        addr,
        close_port_after_each_call=False,
    )

    # All instruments share the same serial connection.
    inst.serial = shared_serial

    inst.mode = minimalmodbus.MODE_RTU

    return inst


# ==================================================
# REGISTER CONVERSION
# ==================================================

def to_float(regs):
    """
    Convert two 16-bit registers into a 32-bit float.
    """

    raw = struct.pack(
        ">I",
        (regs[0] << 16) | regs[1]
    )

    return struct.unpack(">f", raw)[0]


# ==================================================
# READ MODBUS REGISTERS
# ==================================================

def read_one_sync(inst):
    """
    Blocking Modbus read.
    Runs inside a thread executor.
    """

    try:

        # Read voltage
        v_regs = inst.read_registers(
            DC_REG_VOLTAGE,
            2,
            functioncode=3
        )

        # Read current
        i_regs = inst.read_registers(
            DC_REG_CURRENT,
            2,
            functioncode=3
        )

        # Read power
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

        print(
            f"[Modbus] Read error on instrument "
            f"{inst.address}: {e}"
        )

        return None


# ==================================================
# MODBUS POLLER
# ==================================================

class ModbusPoller:

    def __init__(self):

        self.meters = {}

        # Shared serial connection
        self.serial_port = None

        # Track switch state
        self.previous_read_enabled = None


    # --------------------------------------------------
    # CREATE / UPDATE CONTROLLERS
    # --------------------------------------------------

    async def update_meters(self):
        """
        Refresh controller addresses from the database.

        All instruments use the same serial connection.
        """

        addresses = await get_addresses()

        try:

            addresses = [
                int(addr)
                for addr in addresses
            ]

        except (ValueError, TypeError) as e:

            print(
                f"[Modbus] Invalid controller address: {e}"
            )

            return

        # Remove duplicates
        addresses = list(set(addresses))

        # No controllers registered
        if not addresses:

            if self.meters:
                print(
                    "[Modbus] No controllers found. "
                    "Removing instruments."
                )

            self.meters = {}

            return

        # Create shared serial object if needed
        if self.serial_port is None:

            self.serial_port = create_serial_port()

        # Add newly registered controllers
        for addr in addresses:

            if addr not in self.meters:

                try:

                    inst = make_instrument(
                        addr,
                        self.serial_port
                    )

                    self.meters[addr] = inst

                    print(
                        f"[Modbus] Added controller: {addr}"
                    )

                except Exception as e:

                    print(
                        f"[Modbus] Failed to create instrument "
                        f"for {addr}: {e}"
                    )

        # Remove deleted controllers
        current_addresses = set(addresses)

        for addr in list(self.meters.keys()):

            if addr not in current_addresses:

                print(
                    f"[Modbus] Removing controller: {addr}"
                )

                del self.meters[addr]


    # --------------------------------------------------
    # CONNECT COM PORT
    # --------------------------------------------------

    def connect_comport(self):
        """
        Open the COM port when Read Data is ON.
        """

        if self.serial_port is None:

            self.serial_port = create_serial_port()

        try:

            if not self.serial_port.is_open:

                self.serial_port.open()

                print(
                    f"[Modbus] COM port connected: {PORT}"
                )

            return True

        except Exception as e:

            print(
                f"[Modbus] Failed to connect to "
                f"{PORT}: {e}"
            )

            return False


    # --------------------------------------------------
    # DISCONNECT COM PORT
    # --------------------------------------------------

    def disconnect_comport(self):
        """
        Close the COM port when Read Data is OFF.
        """

        if self.serial_port is None:
            return

        try:

            if self.serial_port.is_open:

                self.serial_port.close()

                print(
                    f"[Modbus] COM port disconnected: {PORT}"
                )

        except Exception as e:

            print(
                f"[Modbus] Failed to disconnect "
                f"{PORT}: {e}"
            )


    # --------------------------------------------------
    # POLLING LOOP
    # --------------------------------------------------

    async def poll_forever(self):

        loop = asyncio.get_running_loop()

        print("[Modbus] Poller started.")

        while True:

            try:

                # ======================================
                # 1. CHECK BACKEND SWITCH
                # ======================================

                enabled = await is_read_enabled()

                # Print switch state only when changed
                if enabled != self.previous_read_enabled:

                    if enabled:

                        print(
                            "[Modbus] Read Data ON. "
                            "Connecting to COM port."
                        )

                    else:

                        print(
                            "[Modbus] Read Data OFF. "
                            "Disconnecting COM port."
                        )

                    self.previous_read_enabled = enabled


                # ======================================
                # 2. SWITCH OFF
                # ======================================

                if not enabled:

                    self.disconnect_comport()

                    await asyncio.sleep(POLL_INTERVAL)

                    continue


                # ======================================
                # 3. UPDATE CONTROLLERS
                # ======================================

                await self.update_meters()

                if not self.meters:

                    print(
                        "[Modbus] No controllers available."
                    )

                    self.disconnect_comport()

                    await asyncio.sleep(POLL_INTERVAL)

                    continue


                # ======================================
                # 4. CONNECT COM PORT
                # ======================================

                connected = self.connect_comport()

                if not connected:

                    await asyncio.sleep(POLL_INTERVAL)

                    continue


                # ======================================
                # 5. READ EACH CONTROLLER
                # ======================================

                for addr, inst in list(self.meters.items()):

                    try:

                        # Check switch before reading each meter
                        enabled = await is_read_enabled()

                        if not enabled:

                            print(
                                "[Modbus] Switch OFF. "
                                "Stopping polling cycle."
                            )

                            self.disconnect_comport()

                            break


                        # Read Modbus registers
                        reading = await loop.run_in_executor(
                            None,
                            read_one_sync,
                            inst
                        )


                        # Read failed
                        if reading is None:

                            continue


                        # ==================================
                        # 6. PREPARE DATA
                        # ==================================

                        data = {
                            "controller_no": str(addr),
                            "voltage": reading["voltage"],
                            "amperage": reading["amperage"],
                            "power": reading["power"],
                        }

                        print(
                            f"[Modbus] Read data: {data}"
                        )


                        # ==================================
                        # 7. SAVE DATA
                        # ==================================

                        await save_monitor_data(data)


                    except Exception as e:

                        print(
                            f"[Modbus] Error polling controller "
                            f"{addr}: {e}"
                        )


                    # Small gap between controllers
                    await asyncio.sleep(0.15)


            except asyncio.CancelledError:

                print(
                    "[Modbus] Poller cancelled. "
                    "Shutting down."
                )

                self.disconnect_comport()

                raise


            except Exception as e:

                print(
                    f"[Modbus] Unexpected polling error: {e}"
                )

                self.disconnect_comport()


            # ======================================
            # 8. WAIT BEFORE NEXT POLLING CYCLE
            # ======================================

            await asyncio.sleep(POLL_INTERVAL)