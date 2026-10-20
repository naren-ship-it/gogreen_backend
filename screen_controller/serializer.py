from rest_framework import serializers
from .models import Screen, ScreenPosition, Windows


class ScreenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Screen
        fields = "__all__"


class ScreenPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScreenPosition
        fields = "__all__"


class WindowsSerializer(serializers.ModelSerializer):
    position_details = ScreenPositionSerializer(
        source="position",
        read_only=True,
    )

    active_screen_details = ScreenSerializer(
        source="activee_screen",
        read_only=True,
    )

    class Meta:
        model = Windows
        fields = [
            "id",
            "name",
            "position",
            "activee_screen",
            "is_active",
            "position_details",
            "active_screen_details",
        ]
        read_only_fields = [
            "id",
            "position_details",
            "active_screen_details",
        ]
