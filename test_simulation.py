"""
simulate_meter_push.py
======================
Pushes realistic random meter readings to the UpdateReadingAPIView endpoint
in a loop so you can test your frontend without real hardware.

Usage:
    python simulate_meter_push.py

Ctrl+C to stop.
"""

import random
import time
import requests
from datetime import datetime

# ======================================================================
# CONFIGURATION  -- change these to match your setup
# ======================================================================
SERVER_URL      = "http://localhost:8000/api/update-reading/"
REQUEST_TIMEOUT = 3.0
POLL_INTERVAL   = 1.0      # seconds between each full push cycle5

CONTROLLER_ID_MAP = {
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "10",
    11: "11",
    12: "12",
   

}

# Change these ranges to match actual cycle output
VOLTAGE_RANGE  = (0.5,  0.9)    # realistic low voltage
CURRENT_RANGE  = (0.5,  0.9)    # realistic low current  
POWER_RANGE    = (0.5, 0.9)    # realistic low power (like 0.17)
ENERGY_BASE = 100.0

# ======================================================================
# STATE  -- energy accumulates across cycles like a real meter
# ======================================================================
energy = {addr: ENERGY_BASE + random.uniform(0, 50) for addr in CONTROLLER_ID_MAP}

# ======================================================================
# HELPERS
# ======================================================================

def random_reading(addr):
    """Generate one plausible meter reading for a given slave address."""
    v  = round(random.uniform(*VOLTAGE_RANGE), 2)
    a  = round(random.uniform(*CURRENT_RANGE), 3)
    kw = round(v * a , 3)          # physically consistent power
    # energy creeps up a tiny bit each cycle
    energy[addr] += round(random.uniform(0.001, 0.010), 3)
    return {
        "V":   v,
        "A":   a,
        "kW":  kw,
        "kWh": round(energy[addr], 3),
    }


def push(addr, data):
    """POST one reading to the server. Returns (status_code, response_text)."""
    controller_id = CONTROLLER_ID_MAP[addr]
    payload = {
        "controller_id": controller_id,
        "voltage":        data["V"],
        "amperage":       data["A"],
        "power":          data["kW"],
    }
    try:
        resp = requests.post(SERVER_URL, data=payload, timeout=REQUEST_TIMEOUT)
        return resp.status_code, resp.text[:120]
    except requests.exceptions.RequestException as e:
        return None, str(e)


# ======================================================================
# MAIN LOOP
# ======================================================================

print("=" * 70)
print(f"  Simulated meter push  →  {SERVER_URL}")
print(f"  Controllers : {list(CONTROLLER_ID_MAP.values())}")
print(f"  Interval    : {POLL_INTERVAL}s      Ctrl+C to stop")
print("=" * 70)
print()
print(f"{'Time':<22} {'Controller':<12} {'V':>7} {'A':>7} {'kW':>7} {'kWh':>10}  Status")
print("-" * 75)

try:
    while True:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for addr in CONTROLLER_ID_MAP:
            d = random_reading(addr)
            status_code, body = push(addr, d)
            ctrl = CONTROLLER_ID_MAP[addr]

            if status_code == 200:
                status_str = "✓ 200 OK"
            elif status_code is None:
                status_str = f"✗ ERR  {body}"
            else:
                status_str = f"✗ {status_code}  {body}"

            print(f"{ts:<22} {ctrl:<12} {d['V']:>7.2f} {d['A']:>7.3f} "
                  f"{d['kW']:>7.3f} {d['kWh']:>10.3f}  {status_str}")

        print()   # blank line between cycles for readability
        time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    print("\nSimulation stopped.")