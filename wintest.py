# test_manual.py
import asyncio
import json
import websockets

WINDOW_ID = 1  # use a real window_id from your DB, same screen_id

async def admin_create_window():
    uri = f"ws://localhost:8000/ws/window/admin/{WINDOW_ID}/"
    async with websockets.connect(uri) as ws:
        print(await ws.recv())  # connection_established

        await ws.send(json.dumps({
            "type": "create_window",
            "width": 800, "height": 600, "x": 0, "y": 0,
        }))
        print("1st create:", await ws.recv())

        # Simulate the client app reporting its pid
        # (normally the client connection does this, but for this
        # test just call it from admin too, or open a client ws)
        await ws.send(json.dumps({
            "type": "window_client_connected",
            "window_id": WINDOW_ID,
            "pid": 12345,
        }))

        await asyncio.sleep(0.3)  # let the db write land

        # Now try creating again on the same screen -> should error
        await ws.send(json.dumps({
            "type": "create_window",
            "width": 800, "height": 600, "x": 0, "y": 0,
        }))
        print("2nd create (should fail):", await ws.recv())

# asyncio.run(admin_create_window())

async def test_disconnect_clears_pid():
    uri = f"ws://localhost:8000/ws/window/client/{WINDOW_ID}/"
    ws = await websockets.connect(uri)
    print(await ws.recv())
    await ws.send(json.dumps({
        "type": "window_client_connected",
        "window_id": WINDOW_ID,
        "pid": 99999,
    }))
    await asyncio.sleep(0.2)
    await ws.close()  # simulate client crash/close

    await asyncio.sleep(0.3)

    # Now admin tries create_window again -> should succeed since pid cleared
    async with websockets.connect(f"ws://localhost:8000/ws/window/admin/{WINDOW_ID}/") as admin_ws:
        await admin_ws.recv()
        await admin_ws.send(json.dumps({"type": "create_window", "width": 800, "height": 600}))
        print("create after disconnect (should succeed):", await admin_ws.recv())

asyncio.run(test_disconnect_clears_pid())