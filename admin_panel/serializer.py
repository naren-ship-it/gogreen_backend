from rest_framework import serializers
from core.models import Cycle, Participent, ParticipentCycle, AppTheme,ParticipantCyclingDuration
from django.utils import timezone
from datetime import timedelta

class CycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cycle
        fields = "__all__"


class ParticipentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participent
        fields = "__all__"


class ParticipentCycleSerializer(serializers.ModelSerializer):
    participent_name = serializers.CharField(source="participent.name", read_only=True)
    other_participant_detail = serializers.SerializerMethodField()
    cycle_no = serializers.CharField(source="cycle.cycle_no", read_only=True)
    controller_no = serializers.CharField(source="cycle.controller_no", read_only=True)

    class Meta:
        model = ParticipentCycle
        fields = [
            "id", "cycle", "cycle_no", "controller_no",
            "participent", "participent_name",
            "other_participant", "other_participant_detail",
            "power", "voltage", "amperage",
            "total_power", "total_voltage", "total_amperage",
            "duration", "updated_at",
        ]
        read_only_fields = [
            "total_power", "total_voltage", "total_amperage",
            "power", "voltage", "amperage",
        ]

    def get_other_participant_detail(self, obj):
        return [{"id": p.id, "name": p.name} for p in obj.other_participant.all()]



def format_duration(total_seconds):
    if total_seconds is None:
        total_seconds = 0.0
    total_seconds = max(0.0, total_seconds)
    total_seconds_int = int(round(total_seconds))
    if total_seconds_int < 60:
        return f"{total_seconds_int}s"
    minutes = total_seconds_int // 60
    return f"{minutes}m"

class ParticipentCycleDurationSerializer(serializers.ModelSerializer):
    participent_name = serializers.CharField(source="participent.name", read_only=True)
    other_participant_detail = serializers.SerializerMethodField()
    cycle_no = serializers.CharField(source="cycle.cycle_no", read_only=True)
    controller_no = serializers.CharField(source="cycle.controller_no", read_only=True)

    participant_cycling_duration = serializers.SerializerMethodField()
    participant_cycling_duration_display = serializers.SerializerMethodField()
    participant_cycling_is_ended = serializers.SerializerMethodField()

    class Meta:
        model = ParticipentCycle
        fields = [
            "id", "cycle", "cycle_no", "controller_no",
            "participent", "participent_name",
            "other_participant", "other_participant_detail",
            "power", "voltage", "amperage",
            "total_power", "total_voltage", "total_amperage",
            "duration", "updated_at",
            "participant_cycling_duration",
            "participant_cycling_duration_display",
            "participant_cycling_is_ended",
        ]
        read_only_fields = [
            "total_power", "total_voltage", "total_amperage",
            "power", "voltage", "amperage",
        ]

    def get_other_participant_detail(self, obj):
        """
        Each entry now also carries that other_participant's aggregated
        cycling duration across ALL their sessions (ended sessions summed
        by their actual duration, plus elapsed time for any still-running
        session), a display string, and whether they currently have an
        active (not-ended) session.
        """
        details = []
        for p in obj.other_participant.all():
            seconds, is_ended = self._aggregate_duration_for(p.id)
            details.append({
                "id": p.id,
                "name": p.name,
                "cycling_duration": seconds,
                "cycling_duration_display": (
                    format_duration(seconds) if seconds is not None else None
                ),
                "cycling_is_ended": is_ended,
            })
        return details

    def _get_sessions_for(self, participant_id):
        """
        All ParticipantCyclingDuration rows for the given participant id.
        Cached per-serializer-instance (across all rows being serialized
        in this request/response) so the same participant appearing in
        multiple allocations, or as both the main participant and an
        other_participant, only hits the DB once.
        """
        cache = getattr(self, "_cycling_sessions_cache", None)
        if cache is None:
            cache = {}
            self._cycling_sessions_cache = cache

        if participant_id in cache:
            return cache[participant_id]

        sessions = list(
            ParticipantCyclingDuration.objects
            .filter(participant_id=participant_id)
            .order_by("start_at")
        )
        cache[participant_id] = sessions
        return sessions

    def _aggregate_duration_for(self, participant_id):
        """
        Sums duration across every session for this participant:
          - is_ended=True  -> end_at - start_at
          - is_ended=False -> now - start_at (ongoing)

        Returns (total_seconds, has_active_session).
        total_seconds is None if there are no sessions at all.
        has_active_session is True if any session is currently not ended.
        """
        sessions = self._get_sessions_for(participant_id)
        if not sessions:
            return None, None

        now = timezone.now()
        total = timedelta()
        has_active = False

        for session in sessions:
            if session.is_ended:
                if session.end_at:
                    total += (session.end_at - session.start_at)
                # if is_ended but end_at missing, skip (bad data) or
                # optionally treat as 0 duration
            else:
                has_active = True
                total += (now - session.start_at)

        return total.total_seconds(), has_active

    def get_participant_cycling_duration(self, obj):
        """
        Aggregated duration in seconds (float) across ALL of the main
        participant's cycling sessions. None if no sessions exist.
        """
        seconds, _ = self._aggregate_duration_for(obj.participent_id)
        return seconds

    def get_participant_cycling_duration_display(self, obj):
        seconds = self.get_participant_cycling_duration(obj)
        if seconds is None:
            return None
        return format_duration(seconds)

    def get_participant_cycling_is_ended(self, obj):
        """
        True if the participant has NO currently active (not-ended)
        session — i.e. all sessions ended. False if at least one session
        is still ongoing. None if no sessions exist at all.
        """
        _, has_active = self._aggregate_duration_for(obj.participent_id)
        if has_active is None:
            return None
        return not has_active

    
from django.contrib.auth import authenticate
from rest_framework import serializers


class LoginSerializer(serializers.Serializer):

    username = serializers.CharField()

    password = serializers.CharField(write_only=True)

    def validate(self, attrs):

        username = attrs.get("username")
        password = attrs.get("password")

        user = authenticate(
            username=username,
            password=password,
        )

        if not user:

            raise serializers.ValidationError(
                "Invalid username or password."
            )

        attrs["user"] = user

        return attrs

class AppThemeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppTheme
        fields = "__all__"

class AppThemeListSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppTheme
        fields = ['id','name','is_active']