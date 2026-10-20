
import json

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import transaction

from .models import ScreenPosition, Windows


class WindowConsumer(AsyncWebsocketConsumer):
    """
    WebSocket:
        /ws/window/<role>/<window_id>/

    Communication:
        Admin -> Client (one-way configuration push).

    Admin and client connections for the same Window ID share
    one channel group.
    """

    ADMIN_ROLE = "admin"
    CLIENT_ROLE = "client"

    NUMERIC_FIELDS = {"x", "y", "width", "height"}

    BOOLEAN_FIELDS = {
    "fullscreen",
    "always_on_top",
}

    CONFIGURATION_FIELDS = {
    "x",
    "y",
    "width",
    "height",
    "fullscreen",
    "always_on_top",
}

    # --------------------------------------------------
    # CONNECTION
    # --------------------------------------------------

    async def connect(self):
        kwargs = self.scope["url_route"]["kwargs"]

        self.role = str(kwargs.get("role", "")).strip().lower()
        self.window_id = self._parse_id(kwargs.get("window_id"))

        if self.role not in {self.ADMIN_ROLE, self.CLIENT_ROLE}:
            await self.close(code=4003)
            return

        if self.window_id is None:
            await self.close(code=4000)
            return

        self.window_info = await self.get_window_info(self.window_id)

        if self.window_info is None:
            print(f"Window {self.window_id} not found.")
            await self.close(code=4004)
            return

        self.screen_id = self.window_info["screen_id"]

        # Both admin and client must use the same group name.
        self.group_name = f"window_{self.window_id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

        await self.send_json({
            "type": "connection_established",
            "role": self.role,
            "window_id": self.window_id,
            "screen_id": self.screen_id,
        })

        print(
            f"WebSocket connected: role={self.role}, "
            f"window={self.window_id}, group={self.group_name}"
        )

    async def disconnect(self, close_code):
        group_name = getattr(self, "group_name", None)

        if group_name:
            await self.channel_layer.group_discard(
                group_name,
                self.channel_name,
            )

        print(
            f"WebSocket disconnected: role={getattr(self, 'role', None)}, "
            f"window={getattr(self, 'window_id', None)}, "
            f"code={close_code}"
        )

    # --------------------------------------------------
    # RECEIVE MESSAGES
    # --------------------------------------------------

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            await self.send_error("Text JSON messages are required.")
            return

        try:
            data = json.loads(text_data)
            print(f"received data {data}")
        except (json.JSONDecodeError, TypeError):
            await self.send_error("Invalid JSON.")
            return

        if not isinstance(data, dict):
            await self.send_error("The JSON message must be an object.")
            return
        
        # print(f"----window_client_connected{data}")
        action = data.get("type")

        # # Client is receive-only.
        # if self.role == self.CLIENT_ROLE:
        #     await self.send_error(
        #         "Client connections are receive-only. "
        #         "Only admin connections can send configuration."
        #     )
        #     return

        if action == "change_resolution":
            await self.handle_change_resolution(data)
            
        elif action == "window_client_connected":
            await self.store_pid(data['window_id'],data['pid'])
            print(f"pid stored {data}")
            
        elif action == "get_windows":
            windows = await self.get_windows()

            await self.send_json({
                "type": "windows_list",
                "window_id": self.window_id,
                "screen_id": self.screen_id,
                "windows": windows,
            })

        elif action == "create_window":
            await self.handle_create_window(data)

        else:
            await self.send_error(f"Unknown action: {action}")

    async def send_json(self, data):
        await self.send(text_data=json.dumps(data))

    async def send_error(self, message):
        await self.send_json({
            "type": "error",
            "window_id": getattr(self, "window_id", None),
            "message": message,
        })

    # --------------------------------------------------
    # WINDOW / SCREEN LOOKUP
    # --------------------------------------------------

    @staticmethod
    def _parse_id(value):
        if isinstance(value, bool) or value is None:
            return None

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None

        return parsed if parsed > 0 else None

    @database_sync_to_async
    def get_window_info(self, window_id):
        window = (
            Windows.objects
            .filter(pk=window_id)
            .values("id", "activee_screen_id")
            .first()
        )

        if window is None:
            return None

        return {
            "window_id": window["id"],
            "screen_id": window["activee_screen_id"],
        }

    # --------------------------------------------------
    # ADMIN -> CLIENT CONFIGURATION PUSH
    # --------------------------------------------------

    async def handle_change_resolution(self, data):
        requested_id = self._parse_id(data.get("window_id"))

        # The URL's Window ID is authoritative.
        if requested_id is not None and requested_id != self.window_id:
            await self.send_error(
                f"This connection controls Window {self.window_id} only."
            )
            return

        properties = data.get("properties")

        if not isinstance(properties, dict):
            await self.send_error(
                "'properties' must be a JSON object."
            )
            return

        try:
            print(f"the request properties is {properties}")
            validated = self.validate_properties(properties)

            # Persist configuration before notifying the client.
            result = await self.update_window_properties(
                window_id=self.window_id,
                screen_id=self.screen_id,
                properties=validated,
            )

            if result is None:
                await self.send_error(
                    f"Window {self.window_id} was not found."
                )
                return

            message = {
                "type": "resolution_changed",
                "window_id": self.window_id,
                "screen_id": self.screen_id,
                "properties": result["properties"],
                "window": result,
            }

            # Direct acknowledgement to admin.
            await self.send_json({
                "type": "configuration_pushed",
                "window_id": self.window_id,
                "screen_id": self.screen_id,
                "properties": result["properties"],
                "message": "Configuration saved and sent to the client.",
            })

            # Deliver to client connections in this window's group.
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "window_event",
                    "data": message,
                    "exclude_channel": self.channel_name,
                },
            )

            print(
                f"Admin -> Client | window={self.window_id} | "
                f"properties={result['properties']}"
            )

        except (TypeError, ValueError) as error:
            print(error)
            await self.send_error(str(error))

        except Exception as error:
            print("Configuration push failed:", repr(error))
            await self.send_error(
                "Unable to save or send window configuration."
            )

    @classmethod
    def validate_properties(cls, properties):
        if not isinstance(properties, dict):
            raise ValueError("'properties' must be a JSON object.")

        unknown_fields = set(properties.keys()) - cls.CONFIGURATION_FIELDS

        if unknown_fields:
            raise ValueError(
                "Unsupported configuration fields: "
                + ", ".join(sorted(unknown_fields))
            )

        if not properties:
            raise ValueError("No configuration properties were supplied.")

        validated = {}

        for field, value in properties.items():
            if field in {"width", "height"}:
                validated[field] = cls._valid_dimension(value)

            elif field in {"x", "y"}:
                validated[field] = cls._valid_coordinate(value)

            elif field in cls.BOOLEAN_FIELDS:
                if not isinstance(value, bool):
                    raise ValueError(f"{field} must be true or false.")

                validated[field] = value

        return validated

    @database_sync_to_async
    def update_window_properties(self, window_id, screen_id, properties):
        with transaction.atomic():
            window = (
                Windows.objects
                .select_related("position", "activee_screen")
                .filter(
                    pk=window_id,
                    activee_screen_id=screen_id,
                )
                .first()
            )

            if window is None or window.position is None:
                return None

            position = window.position
            changed_fields = []

            for field, value in properties.items():
                if not hasattr(position, field):
                    raise ValueError(
                        f"ScreenPosition has no '{field}' field. "
                        "Check your Django model."
                    )

                setattr(position, field, value)
                changed_fields.append(field)

            if changed_fields:
                position.save(
                    update_fields=list(dict.fromkeys(changed_fields))
                )

            position.refresh_from_db()
            window.refresh_from_db()

            return self.serialize_window(window)
    # --------------------------------------------------
    # BROADCAST EVENTS
    # --------------------------------------------------

    async def window_event(self, event):
        # Only client connections receive admin broadcasts.
        if self.role != self.CLIENT_ROLE:
            return

        if event.get("exclude_channel") == self.channel_name:
            return

        await self.send_json(event["data"])

    # --------------------------------------------------
    # CREATE WINDOW
    # --------------------------------------------------

    async def handle_create_window(self, data):
        try:
            window = await self.create_window(
                screen_id=self.screen_id,
                width=data.get("width", 1200),
                height=data.get("height", 900),
                x=data.get("x", 0),
                y=data.get("y", 0),
            )

            if window is None:
                await self.send_error(
                    f"Screen {self.screen_id} not found."
                )
                return

            await self.send_json({
                "type": "window_created",
                "window_id": self.window_id,
                "created_window": window,
            })

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "window_event",
                    "data": {
                        "type": "window_created",
                        "window_id": self.window_id,
                        "screen_id": self.screen_id,
                        "window": window,
                    },
                    "exclude_channel": self.channel_name,
                },
            )

        except (TypeError, ValueError) as error:
            await self.send_error(str(error))

        except Exception as error:
            print("Create window failed:", repr(error))
            await self.send_error("Unable to create window.")

    @database_sync_to_async
    def create_window(
        self,
        screen_id,
        width=1200,
        height=900,
        x=0,
        y=0,
    ):
        width = self._valid_dimension(width)
        height = self._valid_dimension(height)
        x = self._valid_coordinate(x)
        y = self._valid_coordinate(y)

        with transaction.atomic():
            from .models import Screen

            screen = Screen.objects.filter(pk=screen_id).first()

            if screen is None:
                return None

            position = ScreenPosition.objects.create(
                name="Window position",
                width=width,
                height=height,
                x=x,
                y=y,
            )

            window = Windows.objects.create(
                name="New Window",
                position=position,
                activee_screen=screen,
            )

            window.name = f"Window {window.pk}"
            window.save(update_fields=["name"])

            return self.serialize_window(window)

    # --------------------------------------------------
    # GET WINDOWS
    # --------------------------------------------------
    
    @database_sync_to_async
    def store_pid(self,window_id,pid):
        try:
            window = Windows.objects.get(id=window_id)
            window.pid = pid
            window.save()
        except Exception as e:
            print("Error While Storing Processor id")
            print(e)

    @database_sync_to_async
    def get_windows(self):
        windows = (
            Windows.objects
            .select_related("position", "activee_screen")
            .filter(activee_screen_id=self.screen_id)
            .order_by("id")
        )

        return [
            self.serialize_window(window)
            for window in windows
        ]

    # --------------------------------------------------
    # VALIDATION HELPERS
    # --------------------------------------------------

    @staticmethod
    def _valid_dimension(value):
        if isinstance(value, bool):
            raise ValueError("Boolean is not a valid dimension.")

        if isinstance(value, float) and not value.is_integer():
            raise ValueError("Dimension must be an integer.")

        if isinstance(value, str):
            value = value.strip()

            if not value or not value.isdigit():
                raise ValueError("Dimension must be a positive integer.")

        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError("Dimension must be an integer.")

        if value <= 0 or value > 16384:
            raise ValueError(
                "Width and height must be between 1 and 16384."
            )

        return value

    @staticmethod
    def _valid_coordinate(value):
        if isinstance(value, bool):
            raise ValueError("Boolean is not a valid coordinate.")

        if isinstance(value, float) and not value.is_integer():
            raise ValueError("Coordinate must be an integer.")

        if isinstance(value, str):
            value = value.strip()

            if (
                not value
                or value in {"+", "-"}
                or not value.lstrip("+-").isdigit()
            ):
                raise ValueError("Coordinate must be an integer.")

        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError("Coordinate must be an integer.")

    # --------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------

    @staticmethod
    def serialize_window(window):
        position = window.position
        screen = window.activee_screen

        return {
            "window_id": window.pk,
            "name": window.name,
            "screen_id": screen.pk,
            "screen_name": screen.name,
            "path": screen.path,
            "properties": {
                "x": position.x,
                "y": position.y,
                "width": position.width,
                "height": position.height,
                "fullscreen": position.fullscreen,
                "always_on_top": position.always_on_top,
            },
        }
