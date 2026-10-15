from rest_framework import serializers
from .models import *


class ScreenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Screen
        fields = "__all__"


class ScreenPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScreenPosition
        fields = "__all__"