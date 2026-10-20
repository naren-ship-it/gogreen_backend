"""Project-level Channels routing.

Defines websocket_urlpatterns which are used by the ASGI application.
"""
from django.urls import path, re_path

from core.consumers import EchoConsumer
from screen_controller.consumers import ScreenConsumer
from screen_controller.window_consumer import WindowConsumer
from core.power_monitor_consumer import PowerMonitorConsumer
from core.group_participant_consumer import GroupRankingConsumer
from core.app_title_consumer import AppTitleConsumer
websocket_urlpatterns = [
    path('ws/', EchoConsumer.as_asgi()),
    re_path(r"ws/screen/(?P<role>\w+)/$", ScreenConsumer.as_asgi()),
    re_path(
    r"^ws/window/(?P<role>\w+)/(?P<window_id>\d+)/$",
    WindowConsumer.as_asgi(),
),
    re_path(
        r"ws/power-monitor/(?P<role>admin|client)/$",
        PowerMonitorConsumer.as_asgi(),
    ),
    re_path('ws/group-ranking/', GroupRankingConsumer.as_asgi()),
    re_path(
        r"ws/app-title/(?P<role>admin|client)/$",
        AppTitleConsumer.as_asgi(),
    ),
]
