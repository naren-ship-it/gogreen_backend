import asyncio
import json
from datetime import timedelta
from collections import defaultdict

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

from .models import PowerMonitor, ActiveParticipent, Cycle

def format_duration(total_seconds):
    """
    Formats a duration in seconds using only minutes and seconds —
    never hours. Minutes accumulate past 60 instead of rolling over
    into an hours unit:
        45      -> "45s"
        150     -> "2m 30s"
        7500     -> "125m 0s"

    Anything under 60s shows seconds only. 60s or more shows minutes
    and remaining seconds together.
    """
    if total_seconds is None:
        total_seconds = 0.0

    total_seconds = max(0.0, total_seconds)
    total_seconds_int = int(round(total_seconds))

    if total_seconds_int < 60:
        return f"{total_seconds_int}s"

    minutes = total_seconds_int // 60
    seconds = total_seconds_int % 60
    return f"{minutes}m"

class PowerMonitorConsumer(AsyncWebsocketConsumer):

    DEFAULT_MINUTES = 2
    MIN_MINUTES = 1
    MAX_MINUTES = 24 * 60  # safety cap

    DEFAULT_NUM_PARTICIPANTS = 4
    MIN_NUM_PARTICIPANTS = 1
    MAX_NUM_PARTICIPANTS = 1000  # safety cap

    POLL_INTERVAL_SECONDS = 0.5

    ROLE_ADMIN = "admin"
    ROLE_CLIENT = "client"
    VALID_ROLES = {ROLE_ADMIN, ROLE_CLIENT}

    async def connect(self):
        self.group_name = "power_monitor"

        self.role = self.get_role_from_route()

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

        self.running = True
        self.task = asyncio.create_task(self.stream_data())

    # ---------- role from the URL path ----------

    def get_role_from_route(self):
        role = self.scope.get("url_route", {}).get("kwargs", {}).get("role")

        if role:
            role = role.strip().lower()

        if role not in self.VALID_ROLES:
            return self.ROLE_ADMIN

        return role

    # ---------- pull live config from ActiveParticipent ----------

    @database_sync_to_async
    def get_active_config(self):
        """
        Reads the *current* ActiveParticipent row (the one you use to drive
        the live view) and converts it into:
            minutes               -> int, derived from the TimeField (00:10:00 -> 10)
            cycle_nos              -> list[str] of cycle_no's tied to that row via the
                                       ManyToMany, or None if none are attached (meaning
                                       "all cycles")
            is_auto_ranking        -> bool, whether to auto-limit to the top N
                                       participants by duration
            number_of_participant  -> int, how many participants to keep when
                                       is_auto_ranking is True

        This is called on every poll tick (not just once at connect) so
        that if you update ActiveParticipent while the socket is open, the
        rolling window, cycle filter, and ranking settings update live
        without a reconnect.
        """
        active = (
            ActiveParticipent.objects
            .prefetch_related("cycle")
            .order_by("-id")
            .first()
        )

        if active is None:
            return self.DEFAULT_MINUTES, None, True, self.DEFAULT_NUM_PARTICIPANTS

        td = active.time_duration  # datetime.time
        minutes = td.hour * 60 + td.minute + (1 if td.second >= 30 else 0)
        minutes = self.clamp_minutes(minutes if minutes > 0 else self.DEFAULT_MINUTES)

        cycle_nos = list(active.cycle.values_list("cycle_no", flat=True))
        cycle_nos = cycle_nos or None

        is_auto_ranking = bool(active.is_auto_ranking)
        number_of_participant = self.clamp_num_participants(
            active.number_of_participant or self.DEFAULT_NUM_PARTICIPANTS
        )

        return minutes, cycle_nos, is_auto_ranking, number_of_participant

    def clamp_minutes(self, minutes):
        if minutes < self.MIN_MINUTES:
            return self.MIN_MINUTES
        if minutes > self.MAX_MINUTES:
            return self.MAX_MINUTES
        return minutes

    def clamp_num_participants(self, number_of_participant):
        if number_of_participant < self.MIN_NUM_PARTICIPANTS:
            return self.MIN_NUM_PARTICIPANTS
        if number_of_participant > self.MAX_NUM_PARTICIPANTS:
            return self.MAX_NUM_PARTICIPANTS
        return number_of_participant

    # ---------- lifecycle ----------

    async def disconnect(self, close_code):
        self.running = False

        if hasattr(self, "task"):
            self.task.cancel()

        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name,
        )

    async def receive(self, text_data=None, bytes_data=None):
        """
        Admin-only. Lets the admin drawer push a new time_duration (minutes),
        cycle selection, and/or auto-ranking settings, which are written
        straight to the ActiveParticipent row that drives the live
        window/filter/ranking for everyone (admins and clients both read it
        on the next poll tick).

        Expected payload:
            {"minutes": 10, "cycles": ["1", "2"]}
            {"minutes": 10}                             # cycles/ranking left untouched
            {"cycles": []}                               # clears cycle filter -> all cycles
            {"is_auto_ranking": true, "number_of_participant": 4}
        """
        if self.role != self.ROLE_ADMIN:
            return

        if not text_data:
            return

        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"type": "error", "message": "invalid_json"}))
            return

        minutes = payload.get("minutes")
        cycles = payload.get("cycles")
        is_auto_ranking = payload.get("is_auto_ranking")
        number_of_participant = payload.get("number_of_participant")
        leaderboard_sort = payload.get("leaderboard_sort")

        try:
            active = await self.update_active_config(
                minutes, cycles, is_auto_ranking, number_of_participant, leaderboard_sort
            )
        except ValueError as exc:
            await self.send(text_data=json.dumps({"type": "error", "message": str(exc)}))
            return

        await self.send(
            text_data=json.dumps(
                {
                    "type": "config_updated",
                    "minutes": active["minutes"],
                    "cycles": active["cycles"],
                    "is_auto_ranking": active["is_auto_ranking"],
                    "number_of_participant": active["number_of_participant"],
                    "leaderboard_sort": active["leaderboard_sort"],
                }
            )
        )

    @database_sync_to_async
    def update_active_config(self, minutes, cycles, is_auto_ranking, number_of_participant, leaderboard_sort=None):
        """
        Writes to the single ActiveParticipent row (created if it doesn't
        exist yet). `minutes` becomes the TimeField time_duration; `cycles`
        (a list of cycle_no strings) replaces the M2M set; `is_auto_ranking`
        and `number_of_participant` control the top-N ranking behavior.
        Any argument can be omitted/None to leave that piece untouched.
        """
        from datetime import time as time_cls

        active = ActiveParticipent.objects.order_by("-id").first()
        if active is None:
            active = ActiveParticipent(time_duration=time_cls(0, self.DEFAULT_MINUTES, 0))
            active.save()

        update_fields = []

        if minutes is not None:
            try:
                minutes_int = self.clamp_minutes(int(minutes))
            except (TypeError, ValueError):
                raise ValueError("minutes must be an integer")
            active.time_duration = time_cls(minutes_int // 60, minutes_int % 60, 0)
            update_fields.append("time_duration")

        if is_auto_ranking is not None:
            if not isinstance(is_auto_ranking, bool):
                raise ValueError("is_auto_ranking must be a boolean")
            active.is_auto_ranking = is_auto_ranking
            update_fields.append("is_auto_ranking")

        if number_of_participant is not None:
            try:
                num_int = self.clamp_num_participants(int(number_of_participant))
            except (TypeError, ValueError):
                raise ValueError("number_of_participant must be an integer")
            active.number_of_participant = num_int
            update_fields.append("number_of_participant")

        if leaderboard_sort is not None:
            if leaderboard_sort not in ("power", "voltage", "duration"):
                raise ValueError("leaderboard_sort must be power, voltage, or duration")
            active.leaderboard_sort = leaderboard_sort
            update_fields.append("leaderboard_sort")

        if update_fields:
            active.save(update_fields=update_fields)

        if cycles is not None:
            if not isinstance(cycles, list):
                raise ValueError("cycles must be a list")
            # Try matching by pk first (integers), fall back to cycle_no strings
            try:
                pks = [int(c) for c in cycles]
                cycle_qs = Cycle.objects.filter(pk__in=pks)
            except (ValueError, TypeError):
                cycle_qs = Cycle.objects.filter(cycle_no__in=[str(c) for c in cycles])
            active.cycle.set(cycle_qs)

        td = active.time_duration
        return {
            "minutes": td.hour * 60 + td.minute,
            "cycles": list(active.cycle.values_list("cycle_no", flat=True)),
            "is_auto_ranking": active.is_auto_ranking,
            "number_of_participant": active.number_of_participant,
            "leaderboard_sort": active.leaderboard_sort,
        }

    # ---------- streaming loop ----------

    async def stream_data(self):
        if self.role == self.ROLE_ADMIN:
            # Admins don't receive the live stream — only clients do.
            return

        try:
            while self.running:
                minutes, cycle_nos, is_auto_ranking, number_of_participant = (
                    await self.get_active_config()
                )

                data = await self.get_chart_data(
                    minutes, cycle_nos, is_auto_ranking, number_of_participant
                )

                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "trend",
                            "timestamp": asyncio.get_running_loop().time(),
                            "window_minutes": minutes,
                            "cycles": cycle_nos,
                            "is_auto_ranking": is_auto_ranking,
                            "number_of_participant": number_of_participant,
                            "generated_at": timezone.now().isoformat(),
                            "series": data,
                        }
                    )
                )

                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass

    # ---------- data query ----------

    @database_sync_to_async
    def get_chart_data(self, minutes, cycle_nos, is_auto_ranking, number_of_participant):
        """
        Returns EVERY reading for each participant within the rolling
        window [now - minutes, now].

        Because `timezone.now()` is evaluated fresh on every call, and
        `minutes`/`cycle_nos`/`is_auto_ranking`/`number_of_participant` are
        re-read from ActiveParticipent on every tick in stream_data(), the
        window, cycle filter, and ranking all track live changes: at 9:40
        with a 10-min ActiveParticipent row you get [9:30, 9:40]; at 9:41
        you get [9:31, 9:41]; if the row's time_duration, cycle set, or
        ranking settings change, the next tick reflects that.

        Each participant's bucket also carries:
          - duration_seconds: raw float, total time actively cycling on
            this allocation (from ParticipentCycle.duration, accumulated
            by the post_save signal on PowerMonitor)
          - duration_display: the same value formatted into the largest
            sensible unit — "45s" under a minute, "3m" under an hour,
            "2h" at an hour or beyond — for direct display in the UI.

        The `is_auto_ranking` flag switches between two mutually exclusive
        modes:
          - True:  cycle_nos is IGNORED. Every participant within the time
                   window is considered, sorted by duration_seconds
                   descending, and truncated to the top
                   `number_of_participant` entries — a leaderboard across
                   everyone, not scoped to any cycle selection. Each
                   returned entry gets a 1-based `rank` field.
          - False: cycle_nos IS applied (or all cycles, if None/empty).
                   Every matching participant is returned, in
                   participant_id order, unranked, no `rank` field.
        """
        now = timezone.now()

        readings = PowerMonitor.objects.select_related(
            "participent",
            "participent__participent",   # ParticipentCycle -> Participent
            "participent__cycle",         # ParticipentCycle -> Cycle
        ).only(
            "current_voltage",
            "current_amperage",
            "current_power",
            "updated_at",
            "participent_id",
            "participent__cycle__cycle_no",
            "participent__participent__name",
            "participent__duration",
        ).order_by("participent_id", "updated_at")

        if minutes is not None:
            cutoff = now - timedelta(minutes=minutes)
            readings = readings.filter(updated_at__gte=cutoff, updated_at__lte=now)

        # Cycle filtering only applies when auto-ranking is OFF. When it's
        # ON, ranking is computed across all participants regardless of
        # cycle selection.
        if not is_auto_ranking and cycle_nos:
            readings = readings.filter(participent__cycle__cycle_no__in=cycle_nos)

        grouped = defaultdict(lambda: {
            "participant_name": None,
            "cycle_no": None,
            "duration_seconds": 0.0,
            "points": [],
        })

        for item in readings:
            key = item.participent_id
            bucket = grouped[key]
            bucket["participant_name"] = item.participent.participent.name
            bucket["cycle_no"] = item.participent.cycle.cycle_no
            duration = item.participent.duration
            bucket["duration_seconds"] = duration.total_seconds() if duration else 0.0
            bucket["points"].append({
                "time": item.updated_at.isoformat(),
                "power": item.current_power,
                "voltage": item.current_voltage,
                "current": item.current_amperage,
            })

        result = [
            {
                "participant_cycle_id": key,
                "participant_name": bucket["participant_name"],
                "cycle_no": bucket["cycle_no"],
                "duration_seconds": bucket["duration_seconds"],
                "duration_display": format_duration(bucket["duration_seconds"]),
                "points": bucket["points"],
            }
            for key, bucket in grouped.items()
        ]

        if is_auto_ranking:
            result.sort(key=lambda entry: entry["duration_seconds"], reverse=True)
            result = result[:number_of_participant]
            for idx, entry in enumerate(result, start=1):
                entry["rank"] = idx

        return result