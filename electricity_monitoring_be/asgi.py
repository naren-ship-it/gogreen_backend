import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "electricity_monitoring_be.settings"
)

from django.core.asgi import get_asgi_application

# Initialize Django FIRST
django_asgi_app = get_asgi_application()

# Import Channels AFTER Django is ready
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

import electricity_monitoring_be.routing as routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(routing.websocket_urlpatterns)
    ),
})