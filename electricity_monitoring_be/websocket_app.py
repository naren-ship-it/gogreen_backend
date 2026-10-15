"""Simple ASGI WebSocket app for development/testing.

This handler accepts connections under paths starting with "/ws" and
echos received text messages prefixed with "ECHO:". It's intentionally
minimal to avoid adding external dependencies like Channels.
"""

async def websocket_app(scope, receive, send):
    if scope.get('type') != 'websocket':
        await send({
            'type': 'websocket.close',
            'code': 1003,
        })
        return

    path = scope.get('path', '')
    if not path.startswith('/ws'):
        # Only handle websocket paths under /ws
        await send({'type': 'websocket.close', 'code': 1000})
        return

    while True:
        event = await receive()

        if event['type'] == 'websocket.connect':
            await send({'type': 'websocket.accept'})

        elif event['type'] == 'websocket.receive':
            text = event.get('text')
            bytes_data = event.get('bytes')

            if text is not None:
                # Echo text messages
                await send({'type': 'websocket.send', 'text': f'ECHO: {text}'})
            elif bytes_data is not None:
                # Echo binary messages
                await send({'type': 'websocket.send', 'bytes': bytes_data})

        elif event['type'] == 'websocket.disconnect':
            break
