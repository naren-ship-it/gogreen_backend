import os
import shutil
import platform
import string
import mimetypes
from typing import Optional, Dict, List
from pathlib import Path

from fastapi import FastAPI, APIRouter, Query, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import csv
import math
import time
import random
import asyncio
import struct
import json

from datetime import datetime
from collections import deque


# ============================================================================
# SAFETY / FILE HELPERS
# ============================================================================

def path_exists_and_valid(path):
    return bool(path) and os.path.exists(path)


def safe_join_name(directory, name):
    """
    Prevent path traversal via crafted names.
    """
    if not name or name.strip() != name:
        return None

    if any(sep in name for sep in ("/", "\\")) or ".." in name:
        return None

    candidate = os.path.join(directory, name)

    directory_real = os.path.realpath(directory)
    candidate_real = os.path.realpath(candidate)

    if os.path.commonpath([directory_real, candidate_real]) != directory_real:
        return None

    return candidate


def _get_windows_drives():
    drives = []

    try:
        from ctypes import windll

        bitmask = windll.kernel32.GetLogicalDrives()

        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drives.append(f"{letter}:\\")

            bitmask >>= 1

    except Exception:
        drives = [
            f"{l}:\\"
            for l in string.ascii_uppercase
            if os.path.exists(f"{l}:\\")
        ]

    return drives


def resp(payload: dict, status_code: int = 200):
    return JSONResponse(
        content=payload,
        status_code=status_code
    )


# ============================================================================
# PATHS
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(
    BASE_DIR,
    "meter_config.json"
)

LOGFILE = os.path.join(
    BASE_DIR,
    "EM2M_Log.csv"
)


# ============================================================================
# DEFAULT METER CONFIGURATION
# ============================================================================
#
# IMPORTANT:
#
# The frontend can now change all of these values.
#
# simulation_mode:
#     True  -> fake/simulation data
#     False -> real RS485 / Modbus
#
# port:
#     COM1, COM2, COM3, etc.
#
# baudrate:
#     9600, 19200, 38400, etc.
#
# poll_interval:
#     seconds between polls
#
# meters:
#     meter name -> Modbus slave ID
#
# ============================================================================

DEFAULT_METER_CONFIG = {
    
    "port": "COM1",
    "baudrate": 9600,
    "poll_interval": 1.0,
    "meters": {
        "Meter1": 1,
        "Meter2": 2,
    },
}


# ============================================================================
# CONFIG LOAD / SAVE
# ============================================================================

def load_meter_config():
    """
    Load meter configuration from JSON.

    If the file doesn't exist or is invalid,
    default configuration is returned.
    """
    # Load AC_COM_PORT from .env if present — overrides meter_config.json port
    # This is set by setup_dialog.py at startup and does not break the existing
    # frontend config flow; the frontend can still update port via PUT /api/meters/config
    def _read_env_port():
        env_path = os.path.join(
            os.path.dirname(BASE_DIR), ".env"
        )
        if not os.path.exists(env_path):
            # try one level up
            env_path = os.path.join(BASE_DIR, ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line.startswith("AC_COM_PORT="):
                        return _line.split("=", 1)[1].strip()
        return None

    env_port = _read_env_port()

    if not os.path.exists(CONFIG_FILE):
        print("[Config] meter_config.json not found.")
        print("[Config] Using default meter configuration.")
        cfg = DEFAULT_METER_CONFIG.copy()
        if env_port:
            cfg["port"] = env_port
            print(f"[Config] AC COM port from .env: {env_port}")
        return cfg

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        # ------------------------------------------------------------
        # Validate basic values
        # ------------------------------------------------------------

        

        port = str(
            config.get(
                "port",
                DEFAULT_METER_CONFIG["port"]
            )
        ).strip()

        baudrate = int(
            config.get(
                "baudrate",
                DEFAULT_METER_CONFIG["baudrate"]
            )
        )

        poll_interval = float(
            config.get(
                "poll_interval",
                DEFAULT_METER_CONFIG["poll_interval"]
            )
        )

        meters = config.get(
            "meters",
            DEFAULT_METER_CONFIG["meters"]
        )

        if not isinstance(meters, dict):
            meters = DEFAULT_METER_CONFIG["meters"].copy()

        cleaned_meters = {}

        for meter_name, slave_id in meters.items():

            meter_name = str(meter_name).strip()

            if not meter_name:
                continue

            try:
                slave_id = int(slave_id)
            except Exception:
                continue

            if slave_id < 1 or slave_id > 247:
                continue

            cleaned_meters[meter_name] = slave_id

        if not cleaned_meters:
            cleaned_meters = DEFAULT_METER_CONFIG["meters"].copy()

        final_port = env_port if env_port else (port or DEFAULT_METER_CONFIG["port"])
        if env_port:
            print(f"[Config] AC COM port overridden by .env: {env_port}")

        return {
            
            "port": final_port,
            "baudrate": baudrate,
            "poll_interval": max(0.1, poll_interval),
            "meters": cleaned_meters,
        }

    except Exception as e:

        print(f"[Config] Failed to load config: {e}")
        print("[Config] Falling back to defaults.")

        return DEFAULT_METER_CONFIG.copy()


def save_meter_config():
    """
    Persist the current configuration to meter_config.json.
    """

    config_to_save = {
        
        "port": meter_config["port"],
        "baudrate": meter_config["baudrate"],
        "poll_interval": meter_config["poll_interval"],
        "meters": meter_config["meters"],
    }

    temp_file = CONFIG_FILE + ".tmp"

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                config_to_save,
                f,
                indent=4
            )

        os.replace(
            temp_file,
            CONFIG_FILE
        )

        print("[Config] Configuration saved.")

    except Exception as e:

        print(f"[Config] Failed to save configuration: {e}")

        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass


# ============================================================================
# GLOBAL CONFIG
# ============================================================================

meter_config = load_meter_config()


# ============================================================================
# HISTORY
# ============================================================================

HISTORY_LIMIT = 3600


# ============================================================================
# MODBUS REGISTER CONFIGURATION
# ============================================================================

REGISTERS = {

    # name       -> (register, function code)
    "Voltage_V": (20, 4),
    "Current_A": (10, 4),
    "Power_W": (14, 4),

}


# ============================================================================
# IN-MEMORY STORE
# ============================================================================

history: Dict[str, deque] = {}

latest: Dict[str, Dict] = {}

meter_status: Dict[str, bool] = {}


def rebuild_meter_storage():

    global history
    global latest
    global meter_status

    existing_history = history

    history = {}

    latest = {}

    meter_status = {}

    for meter_name in meter_config["meters"]:

        if meter_name in existing_history:

            history[meter_name] = existing_history[meter_name]

        else:

            history[meter_name] = deque(
                maxlen=HISTORY_LIMIT
            )

        meter_status[meter_name] = False


rebuild_meter_storage()


# ============================================================================
# CSV
# ============================================================================

def ensure_csv():

    if not os.path.exists(LOGFILE):

        header = ["Timestamp"]

        for meter in meter_config["meters"]:

            for reg in REGISTERS:

                header.append(
                    f"{meter}_{reg}"
                )

        with open(
            LOGFILE,
            "w",
            newline="",
            encoding="utf-8"
        ) as f:

            csv.writer(f).writerow(header)


def append_csv(
    timestamp: str,
    readings: Dict[str, Dict]
):

    row = [timestamp]

    for meter in meter_config["meters"]:

        for reg in REGISTERS:

            val = readings.get(
                meter,
                {}
            ).get(reg)

            row.append(
                f"{val:.4f}"
                if val is not None
                else ""
            )

    try:

        with open(
            LOGFILE,
            "a",
            newline="",
            encoding="utf-8"
        ) as f:

            csv.writer(f).writerow(row)

    except Exception as e:

        print(f"[CSV] Write failed: {e}")


# ============================================================================
# SIMULATION
# ============================================================================

# _sim_phase = {}


# def rebuild_simulation_phases():

#     global _sim_phase

#     _sim_phase = {
#         name: random.uniform(
#             0,
#             2 * math.pi
#         )
#         for name in meter_config["meters"]
#     }


# rebuild_simulation_phases()


# def simulate_reading(
#     meter_name: str
# ) -> Dict[str, float]:

#     if meter_name not in _sim_phase:

#         _sim_phase[meter_name] = random.uniform(
#             0,
#             2 * math.pi
#         )

#     t = time.time()

#     phase = _sim_phase[meter_name]

#     voltage = (
#         230.0
#         + 5.0 * math.sin(
#             t / 60 + phase
#         )
#     )

#     current = (
#         4.0
#         + 1.5 * math.sin(
#             t / 30 + phase
#         )
#         + random.uniform(
#             -0.1,
#             0.1
#         )
#     )

#     power = (
#         voltage
#         * current
#         * random.uniform(
#             0.95,
#             1.0
#         )
#     )

#     return {

#         "Voltage_V": round(
#             voltage,
#             3
#         ),

#         "Current_A": round(
#             max(current, 0),
#             3
#         ),

#         "Power_W": round(
#             max(power, 0),
#             3
#         ),

#     }


# ============================================================================
# REAL MODBUS
# ============================================================================

_instruments = {}


def close_modbus():

    global _instruments

    for name, inst in list(
        _instruments.items()
    ):

        try:

            if hasattr(inst, "serial"):

                if inst.serial.is_open:
                    inst.serial.close()

        except Exception:
            pass

    _instruments.clear()

    print("[Modbus] Instruments closed.")


def init_modbus():

    global _instruments

    close_modbus()

    try:

        import minimalmodbus
        import serial

        port = meter_config["port"]
        baudrate = meter_config["baudrate"]

        print(
            f"[Modbus] Initialising port={port}, "
            f"baudrate={baudrate}"
        )

        for name, slave_id in meter_config["meters"].items():

            try:

                inst = minimalmodbus.Instrument(
                    port,
                    slave_id
                )

                inst.serial.baudrate = baudrate
                inst.serial.bytesize = 8
                inst.serial.parity = serial.PARITY_NONE
                inst.serial.stopbits = 1
                inst.serial.timeout = 1

                inst.mode = minimalmodbus.MODE_RTU

                inst.debug = False

                inst.close_port_after_each_call = True

                _instruments[name] = inst

                print(
                    f"[Modbus] {name} "
                    f"-> slave {slave_id}"
                )

            except Exception as e:

                print(
                    f"[Modbus] Failed to initialise "
                    f"{name}: {e}"
                )

        print(
            f"[Modbus] {len(_instruments)} "
            f"instrument(s) initialised."
        )

    except Exception as e:

        print(
            f"[Modbus] Import/init failed: {e}"
        )


def read_float_modbus(
    inst,
    register: int,
    functioncode: int = 4
) -> float:

    regs = inst.read_registers(
        register,
        2,
        functioncode=functioncode
    )

    data = struct.pack(
        ">HH",
        regs[1],
        regs[0]
    )

    return struct.unpack(
        ">f",
        data
    )[0]


def real_reading(
    meter_name: str
) -> Dict[str, Optional[float]]:

    inst = _instruments.get(
        meter_name
    )

    result = {}

    if inst is None:

        return {
            k: None
            for k in REGISTERS
        }

    for reg_name, (
        reg,
        fc
    ) in REGISTERS.items():

        try:

            result[reg_name] = round(
                read_float_modbus(
                    inst,
                    reg,
                    fc
                ),
                3
            )

        except Exception as e:

            print(
                f"[Modbus FAIL] "
                f"{meter_name}/{reg_name}: {e}"
            )

            result[reg_name] = None

    return result


# ============================================================================
# WEBSOCKET MANAGER
# ============================================================================

class ConnectionManager:

    def __init__(self):

        self.active: List[WebSocket] = []

    async def connect(
        self,
        ws: WebSocket
    ):

        await ws.accept()

        self.active.append(
            ws
        )

    def disconnect(
        self,
        ws: WebSocket
    ):

        if ws in self.active:

            self.active.remove(
                ws
            )

    async def broadcast(
        self,
        data: dict
    ):

        dead = []

        for ws in list(self.active):

            try:

                await ws.send_json(
                    data
                )

            except Exception:

                dead.append(ws)

        for ws in dead:

            self.disconnect(ws)


manager = ConnectionManager()


# ============================================================================
# WEBSOCKET PAYLOAD
# ============================================================================

def build_ws_payload(
    ts: str,
    readings: Dict[str, Dict]
) -> dict:

    meters_out = []

    for meter_name, data in readings.items():

        meters_out.append({

            "meter_name":
                meter_name,

            "slave_id":
                meter_config["meters"].get(
                    meter_name
                ),

            "online":
                meter_status.get(
                    meter_name,
                    False
                ),

            **{
                k: (
                    v
                    if v is not None
                    else 0
                )
                for k, v in data.items()
            },

        })

    return {

        "type": "live",

        "timestamp": ts,

        

        "meters":
            meters_out,

    }


# ============================================================================
# POLL LOOP
# ============================================================================
async def poll_meters():
    ensure_csv()
    current_port = None
    current_baudrate = None

    while True:
        try:
            port     = meter_config["port"]
            baudrate = meter_config["baudrate"]

            if port != current_port or baudrate != current_baudrate:
                print("[Meter] Configuration changed — reinitialising Modbus.")
                init_modbus()
                current_port     = port
                current_baudrate = baudrate

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            readings: Dict[str, Dict] = {}

            for meter_name in list(meter_config["meters"].keys()):
                data = real_reading(meter_name)
                ok   = any(v is not None for v in data.values())
                meter_status[meter_name] = ok
                readings[meter_name]     = data

                record = {"timestamp": ts, **data}
                if meter_name not in history:
                    history[meter_name] = deque(maxlen=HISTORY_LIMIT)
                history[meter_name].append(record)
                latest[meter_name] = record

            append_csv(ts, readings)
            await manager.broadcast(build_ws_payload(ts, readings))

            interval = max(0.1, float(meter_config["poll_interval"]))
            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            close_modbus()
            raise
        except Exception as e:
            print(f"[Poll] Unexpected error: {e}")
            await asyncio.sleep(1)

# ============================================================================
# REQUEST MODELS
# ============================================================================

class CreateFolderBody(BaseModel):

    path: str
    name: str


class RenameItemBody(BaseModel):

    path: str
    new_name: str


class CopyItemBody(BaseModel):

    source_path: str
    destination_path: str


class MoveItemBody(BaseModel):

    source_path: str
    destination_path: str


class DeleteItemBody(BaseModel):

    path: str


# ============================================================================
# FRONTEND METER CONFIG MODELS
# ============================================================================

class MeterConfigBody(BaseModel):

   
    port: str = "COM1"

    baudrate: int = Field(
        default=9600,
        ge=300,
        le=1000000
    )

    poll_interval: float = Field(
        default=1.0,
        ge=0.1,
        le=3600
    )


class MeterSlaveBody(BaseModel):

    meter_name: str

    slave_id: int = Field(
        ge=1,
        le=247
    )


class FullMeterConfigBody(BaseModel):
    

    port: str = "COM1"

    baudrate: int = Field(
        default=9600,
        ge=300,
        le=1000000
    )

    poll_interval: float = Field(
        default=1.0,
        ge=0.1,
        le=3600
    )

    meters: List[MeterSlaveBody]


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter()


# ============================================================================
# FILE EXPLORER
# ============================================================================

@router.get("/file-explorer")
def file_explorer(
    path: Optional[str] = Query(default="")
):

    requested_path = path or ""

    if not requested_path:

        if platform.system() == "Windows":

            drives = _get_windows_drives()

            return resp({

                "status": True,

                "current_path": None,

                "parent_path": None,

                "items": [

                    {
                        "name": d,
                        "path": d,
                        "type": "drive"
                    }

                    for d in drives

                ],

            })

        else:

            requested_path = "/"

    if not os.path.exists(
        requested_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Path does not exist."
            },
            400
        )

    if not os.path.isdir(
        requested_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Path is not a directory."
            },
            400
        )

    try:

        entries = os.listdir(
            requested_path
        )

    except PermissionError:

        return resp(
            {
                "status": False,
                "message":
                    "Permission denied for this folder."
            },
            403
        )

    folders = []
    files = []

    for entry in sorted(
        entries,
        key=str.lower
    ):

        full_path = os.path.join(
            requested_path,
            entry
        )

        try:

            if os.path.isdir(
                full_path
            ):

                folders.append({

                    "name": entry,

                    "path": full_path,

                    "type": "folder",

                })

            else:

                files.append({

                    "name": entry,

                    "path": full_path,

                    "type": "file",

                    "size":
                        os.path.getsize(
                            full_path
                        ),

                    "extension":
                        os.path.splitext(
                            entry
                        )[1].lstrip("."),

                })

        except (
            PermissionError,
            FileNotFoundError,
            OSError
        ):

            continue

    parent_path = os.path.dirname(
        requested_path.rstrip("\\/")
    ) or None

    return resp({

        "status": True,

        "current_path":
            requested_path,

        "parent_path":
            parent_path,

        "items":
            folders + files,

    })


@router.post("/file-explorer/create-folder")
def create_folder(
    body: CreateFolderBody
):

    directory = body.path

    name = body.name

    if not directory or not name:

        return resp(
            {
                "status": False,
                "message":
                    "'path' and 'name' are required."
            },
            400
        )

    if not os.path.isdir(
        directory
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Target directory does not exist."
            },
            400
        )

    new_path = safe_join_name(
        directory,
        name.strip()
    )

    if not new_path:

        return resp(
            {
                "status": False,
                "message":
                    "Invalid folder name."
            },
            400
        )

    if os.path.exists(
        new_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "A file or folder with that name already exists."
            },
            400
        )

    try:

        os.makedirs(
            new_path
        )

    except PermissionError:

        return resp(
            {
                "status": False,
                "message":
                    "Permission denied."
            },
            403
        )

    except OSError as e:

        return resp(
            {
                "status": False,
                "message":
                    f"Could not create folder: {str(e)}"
            },
            400
        )

    return resp(
        {
            "status": True,
            "message":
                "Folder created.",
            "path":
                new_path
        },
        201
    )


@router.post("/file-explorer/rename")
def rename_item(
    body: RenameItemBody
):

    item_path = body.path

    new_name = body.new_name

    if not item_path or not new_name:

        return resp(
            {
                "status": False,
                "message":
                    "'path' and 'new_name' are required."
            },
            400
        )

    if not os.path.exists(
        item_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Item does not exist."
            },
            400
        )

    parent_dir = os.path.dirname(
        item_path.rstrip("\\/")
    )

    new_path = safe_join_name(
        parent_dir,
        new_name.strip()
    )

    if not new_path:

        return resp(
            {
                "status": False,
                "message":
                    "Invalid new name."
            },
            400
        )

    if os.path.exists(
        new_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "A file or folder with that name already exists."
            },
            400
        )

    try:

        os.rename(
            item_path,
            new_path
        )

    except PermissionError:

        return resp(
            {
                "status": False,
                "message":
                    "Permission denied."
            },
            403
        )

    except OSError as e:

        return resp(
            {
                "status": False,
                "message":
                    f"Could not rename: {str(e)}"
            },
            400
        )

    return resp(
        {
            "status": True,
            "message": "Renamed.",
            "path": new_path
        }
    )


@router.post("/file-explorer/copy")
def copy_item(
    body: CopyItemBody
):

    source_path = body.source_path

    destination_path = body.destination_path

    if not source_path or not destination_path:

        return resp(
            {
                "status": False,
                "message":
                    "'source_path' and 'destination_path' are required."
            },
            400
        )

    if not os.path.exists(
        source_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Source does not exist."
            },
            400
        )

    if not os.path.isdir(
        destination_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Destination folder does not exist."
            },
            400
        )

    name = os.path.basename(
        source_path.rstrip("\\/")
    )

    target_path = safe_join_name(
        destination_path,
        name
    )

    if not target_path:

        return resp(
            {
                "status": False,
                "message":
                    "Invalid destination."
            },
            400
        )

    source_real = os.path.realpath(
        source_path
    )

    dest_real = os.path.realpath(
        destination_path
    )

    if (
        os.path.isdir(source_path)
        and (
            dest_real == source_real
            or dest_real.startswith(
                source_real + os.sep
            )
        )
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Can't copy a folder into itself."
            },
            400
        )

    if os.path.exists(
        target_path
    ):

        base, ext = os.path.splitext(
            name
        )

        counter = 1

        while os.path.exists(
            target_path
        ):

            new_name = (
                f"{base} (copy {counter}){ext}"
                if ext or os.path.isfile(source_path)
                else
                f"{base} (copy {counter})"
            )

            target_path = os.path.join(
                destination_path,
                new_name
            )

            counter += 1

    try:

        if os.path.isdir(
            source_path
        ):

            shutil.copytree(
                source_path,
                target_path
            )

        else:

            shutil.copy2(
                source_path,
                target_path
            )

    except PermissionError:

        return resp(
            {
                "status": False,
                "message":
                    "Permission denied."
            },
            403
        )

    except (
        shutil.Error,
        OSError
    ) as e:

        return resp(
            {
                "status": False,
                "message":
                    f"Could not copy: {str(e)}"
            },
            400
        )

    return resp(
        {
            "status": True,
            "message": "Copied.",
            "path": target_path
        }
    )


@router.post("/file-explorer/move")
def move_item(
    body: MoveItemBody
):

    source_path = body.source_path

    destination_path = body.destination_path

    if not source_path or not destination_path:

        return resp(
            {
                "status": False,
                "message":
                    "'source_path' and 'destination_path' are required."
            },
            400
        )

    if not os.path.exists(
        source_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Source does not exist."
            },
            400
        )

    if not os.path.isdir(
        destination_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Destination folder does not exist."
            },
            400
        )

    name = os.path.basename(
        source_path.rstrip("\\/")
    )

    target_path = safe_join_name(
        destination_path,
        name
    )

    if not target_path:

        return resp(
            {
                "status": False,
                "message":
                    "Invalid destination."
            },
            400
        )

    source_real = os.path.realpath(
        source_path
    )

    dest_real = os.path.realpath(
        destination_path
    )

    if (
        os.path.isdir(source_path)
        and (
            dest_real == source_real
            or dest_real.startswith(
                source_real + os.sep
            )
        )
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Can't move a folder into itself."
            },
            400
        )

    if os.path.exists(
        target_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "A file or folder with that name already exists there."
            },
            400
        )

    try:

        shutil.move(
            source_path,
            target_path
        )

    except PermissionError:

        return resp(
            {
                "status": False,
                "message":
                    "Permission denied."
            },
            403
        )

    except (
        shutil.Error,
        OSError
    ) as e:

        return resp(
            {
                "status": False,
                "message":
                    f"Could not move: {str(e)}"
            },
            400
        )

    return resp(
        {
            "status": True,
            "message": "Moved.",
            "path": target_path
        }
    )


@router.post("/file-explorer/delete")
def delete_item(
    body: DeleteItemBody
):

    item_path = body.path

    if not item_path:

        return resp(
            {
                "status": False,
                "message":
                    "'path' is required."
            },
            400
        )

    if not os.path.exists(
        item_path
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Item does not exist."
            },
            400
        )

    try:

        if os.path.isdir(
            item_path
        ):

            shutil.rmtree(
                item_path
            )

        else:

            os.remove(
                item_path
            )

    except PermissionError:

        return resp(
            {
                "status": False,
                "message":
                    "Permission denied."
            },
            403
        )

    except OSError as e:

        return resp(
            {
                "status": False,
                "message":
                    f"Could not delete: {str(e)}"
            },
            400
        )

    return resp(
        {
            "status": True,
            "message":
                "Deleted."
        }
    )


@router.get("/file-explorer/download")
def download_file(
    path: str = Query(...)
):

    item_path = path

    if not item_path:

        return resp(
            {
                "status": False,
                "message":
                    "'path' query param is required."
            },
            400
        )

    if (
        not os.path.exists(item_path)
        or not os.path.isfile(item_path)
    ):

        return resp(
            {
                "status": False,
                "message":
                    "File not found."
            },
            404
        )

    content_type, _ = mimetypes.guess_type(
        item_path
    )

    content_type = (
        content_type
        or "application/octet-stream"
    )

    try:

        filename = os.path.basename(
            item_path
        )

        return FileResponse(
            path=item_path,
            media_type=content_type,
            filename=filename
        )

    except PermissionError:

        return resp(
            {
                "status": False,
                "message":
                    "Permission denied."
            },
            403
        )


# ============================================================================
# METER CONFIGURATION API
# ============================================================================
#
# GET /api/meters/config
#
# Frontend uses this to load configuration.
#
# PUT /api/meters/config
#
# Frontend uses this to save all configuration.
#
# POST /api/meters/config/meter
#
# Add/update one meter.
#
# DELETE /api/meters/config/meter/{meter_name}
#
# Remove one meter.
#
# ============================================================================


@router.get("/meters/config")
def get_meter_config():

    return {

        "status": True,

        "config": {

            
            "port":
                meter_config[
                    "port"
                ],

            "baudrate":
                meter_config[
                    "baudrate"
                ],

            "poll_interval":
                meter_config[
                    "poll_interval"
                ],

        },

        "meters": [

            {

                "meter_name":
                    name,

                "slave_id":
                    slave_id,

                "online":
                    meter_status.get(
                        name,
                        False
                    ),

            }

            for name, slave_id
            in meter_config[
                "meters"
            ].items()

        ],

    }


@router.put("/meters/config")
async def update_meter_config(
    body: FullMeterConfigBody
):

    global meter_config

    # ------------------------------------------------------------
    # Validate meters
    # ------------------------------------------------------------

    cleaned_meters = {}

    for meter in body.meters:

        meter_name = meter.meter_name.strip()
        slave_id = meter.slave_id

        if not meter_name:
            return resp(
                {
                    "status": False,
                    "message": "Meter name cannot be empty."
                },
                400
            )

        if len(meter_name) > 100:
            return resp(
                {
                    "status": False,
                    "message":
                        f"Meter name '{meter_name}' is too long."
                },
                400
            )

        if meter_name in cleaned_meters:
            return resp(
                {
                    "status": False,
                    "message":
                        f"Duplicate meter name '{meter_name}'."
                },
                400
            )

        cleaned_meters[meter_name] = slave_id





    # ------------------------------------------------------------
    # Check duplicate slave IDs
    # ------------------------------------------------------------

    slave_ids = list(
        cleaned_meters.values()
    )

    if len(slave_ids) != len(
        set(slave_ids)
    ):

        return resp(
            {
                "status": False,
                "message":
                    "Each meter must have a unique slave ID."
            },
            400
        )

    # ------------------------------------------------------------
    # Validate port
    # ------------------------------------------------------------

    port = body.port.strip()

    if not port:

        return resp(
            {
                "status": False,
                "message":
                    "RS485 COM port cannot be empty."
            },
            400
        )

    # ------------------------------------------------------------
    # Update configuration
    # ------------------------------------------------------------

    meter_config = {

        

        "port":
            port,

        "baudrate":
            int(
                body.baudrate
            ),

        "poll_interval":
            max(
                0.1,
                float(
                    body.poll_interval
                )
            ),

        "meters":
            cleaned_meters,

    }

    # ------------------------------------------------------------
    # Rebuild storage
    # ------------------------------------------------------------

    rebuild_meter_storage()

    # rebuild_simulation_phases()

    # ------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------

    save_meter_config()

    # ------------------------------------------------------------
    # If real mode, reinitialize Modbus immediately
    # ------------------------------------------------------------

  

    init_modbus()

    # ------------------------------------------------------------
    # Broadcast configuration to frontend
    # ------------------------------------------------------------

    await manager.broadcast({

        "type":
            "config_updated",

       

        "config":
            meter_config,

    })

    return {

        "status": True,

        "message":
            "Meter configuration updated successfully.",

        "config": {

           

            "port":
                meter_config[
                    "port"
                ],

            "baudrate":
                meter_config[
                    "baudrate"
                ],

            "poll_interval":
                meter_config[
                    "poll_interval"
                ],

        },

        "meters": [

            {

                "meter_name":
                    name,

                "slave_id":
                    slave_id,

                "online":
                    meter_status.get(
                        name,
                        False
                    ),

            }

            for name, slave_id
            in meter_config[
                "meters"
            ].items()

        ],

    }


@router.post("/meters/config/meter")
def add_or_update_meter(
    body: MeterSlaveBody
):

    global meter_config

    meter_name = body.meter_name.strip()

    if not meter_name:

        return resp(
            {
                "status": False,
                "message":
                    "Meter name is required."
            },
            400
        )

    slave_id = int(
        body.slave_id
    )

    # ------------------------------------------------------------
    # Prevent duplicate slave ID
    # ------------------------------------------------------------

    for existing_name, existing_id in meter_config[
        "meters"
    ].items():

        if (
            existing_name != meter_name
            and existing_id == slave_id
        ):

            return resp(
                {
                    "status": False,
                    "message":
                        f"Slave ID {slave_id} is already assigned to {existing_name}."
                },
                400
            )

    meter_config[
        "meters"
    ][meter_name] = slave_id

    rebuild_meter_storage()

    # rebuild_simulation_phases()

    save_meter_config()

    return {

        "status": True,

        "message":
            f"{meter_name} saved successfully.",

        "meter": {

            "meter_name":
                meter_name,

            "slave_id":
                slave_id,

        },

    }


@router.delete(
    "/meters/config/meter/{meter_name}"
)
def delete_meter(
    meter_name: str
):

    global meter_config

    if meter_name not in meter_config[
        "meters"
    ]:

        return resp(
            {
                "status": False,
                "message":
                    f"Meter '{meter_name}' does not exist."
            },
            404
        )

    if len(
        meter_config["meters"]
    ) <= 1:

        return resp(
            {
                "status": False,
                "message":
                    "At least one meter must remain configured."
            },
            400
        )

    del meter_config[
        "meters"
    ][meter_name]

    rebuild_meter_storage()

    # rebuild_simulation_phases()

    save_meter_config()

    # Remove Modbus instrument if present
    _instruments.pop(
        meter_name,
        None
    )

    return {

        "status": True,

        "message":
            f"{meter_name} removed successfully.",

    }


# ============================================================================
# METER LATEST
# ============================================================================

@router.get("/meters/latest")
def get_latest():

    return {

        "status": True,

        "timestamp":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "meters": [

            {

                "meter_name":
                    name,

                "slave_id":
                    meter_config[
                        "meters"
                    ][name],

                "online":
                    meter_status.get(
                        name,
                        False
                    ),

                **{

                    k: (
                        v
                        if v is not None
                        else 0
                    )

                    for k, v
                    in latest.get(
                        name,
                        {}
                    ).items()

                    if k != "timestamp"

                },

            }

            for name
            in meter_config[
                "meters"
            ]

        ],

    }


# ============================================================================
# METER HISTORY
# ============================================================================

@router.get("/meters/history")
def get_history(

    meter: Optional[str] =
        Query(
            default=None,
            description=
                "Meter name, e.g. Meter1"
        ),

    limit: int =
        Query(
            default=60,
            ge=1,
            le=HISTORY_LIMIT
        ),

):

    if (
        meter
        and meter not in history
    ):

        return JSONResponse(
            {
                "status": False,
                "message":
                    f"Unknown meter '{meter}'"
            },
            400
        )

    names = (
        [meter]
        if meter
        else list(
            meter_config[
                "meters"
            ].keys()
        )
    )

    result = {}

    for name in names:

        result[name] = list(
            history.get(
                name,
                []
            )
        )[-limit:]

    return {

        "status": True,

        "history":
            result,

    }


# ============================================================================
# METER STATUS
# ============================================================================

@router.get("/meters/status")
def get_status():

    return {

        "status": True,

     

        "meters": [

            {

                "meter_name":
                    name,

                "slave_id":
                    meter_config[
                        "meters"
                    ][name],

                "online":
                    meter_status.get(
                        name,
                        False
                    ),

            }

            for name
            in meter_config[
                "meters"
            ]

        ],

    }

# ============================================================================
# COM PORT DISCOVERY
# ============================================================================
@router.get("/meters/ports")
def get_available_ports():
    """
    Returns all available COM ports detected on this machine.
    Replaces the need to run test.py manually.
    """
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        port_list = []
        for port in sorted(ports, key=lambda p: p.device):
            port_list.append({
                "device":       port.device,
                "description":  port.description or "Unknown",
                "manufacturer": port.manufacturer or "Unknown",
                "vid_pid": (
                    f"{port.vid:04X}:{port.pid:04X}"
                    if port.vid and port.pid
                    else None
                ),
            })

        print("[COM PORTS] Detected:")
        for port in port_list:
            print(
                f"  {port['device']} - "
                f"{port['description']}")
        return {
            "status": True,
            "ports":  port_list,
        }
    except ImportError:
        return resp(
            {
                "status": False,
                "message": "pyserial is not installed. Run: pip install pyserial",
            },
            500,
        )
    except Exception as e:
        return resp(
            {"status": False, "message": f"Failed to list ports: {e}"},
            500,
        )


# ============================================================================
# CSV DOWNLOAD
# ============================================================================

@router.get("/meters/download-csv")
def download_csv():

    if not os.path.exists(
        LOGFILE
    ):

        return JSONResponse(
            {
                "status": False,
                "message":
                    "No log file yet."
            },
            404
        )

    return FileResponse(

        path=LOGFILE,

        media_type="text/csv",

        filename=(
            "EM2M_Log_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            ".csv"
        ),

    )


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Go Green Energy Meter API"
)


origins = [

    "http://localhost:5173",

    "http://127.0.0.1:5173",

<<<<<<< HEAD
    # Tauri frontend
    "http://localhost:1420",
    "http://127.0.0.1:1420",

=======
>>>>>>> feature/window_manager
]


app.add_middleware(

    CORSMiddleware,

    allow_origins=origins,

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)


app.include_router(
    router,
    prefix="/api"
)


# ============================================================================
# WEBSOCKET
# ============================================================================

@app.websocket(
    "/ws/meters"
)
async def websocket_endpoint(
    websocket: WebSocket
):

    await manager.connect(
        websocket
    )

    # ------------------------------------------------------------
    # Immediately send current data
    # ------------------------------------------------------------

    if latest:

        ts = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        await websocket.send_json(

            build_ws_payload(

                ts,

                {

                    n: {
                        k: v
                        for k, v
                        in latest[n].items()
                        if k != "timestamp"
                    }

                    for n
                    in meter_config[
                        "meters"
                    ]

                    if n in latest

                }

            )

        )

    try:

        while True:

            await websocket.receive_text()

    except WebSocketDisconnect:

        manager.disconnect(
            websocket
        )

    except Exception:

        manager.disconnect(
            websocket
        )


# ============================================================================
# STARTUP
# ============================================================================

@app.on_event(
    "startup"
)
async def startup():

    print("")
    print("=" * 70)
    print(" GO GREEN ENERGY METER SERVER")
    print("=" * 70)

    

    print(
        f"Port       : "
        f"{meter_config['port']}"
    )

    print(
        f"Baudrate   : "
        f"{meter_config['baudrate']}"
    )

    print(
        f"Interval   : "
        f"{meter_config['poll_interval']} sec"
    )

    print(
        f"Meters     : "
        f"{meter_config['meters']}"
    )

    print(
        f"Config     : "
        f"{CONFIG_FILE}"
    )

    print("=" * 70)
    print("")

    asyncio.create_task(
        poll_meters()
    )


# ============================================================================
# ROOT
# ============================================================================

@app.get("/")
def root():

    return {

        "status": True,

        "message":
            "Go Green Energy Meter API is running.",

        "configuration":
            "/api/meters/config",

        "websocket":
            "/ws/meters",

    }


# ============================================================================
# RUN DIRECTLY
# ============================================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        "main:app",

        host="0.0.0.0",

        port=8002,

        reload=True

    )