from django.db import models
from datetime import timedelta
from django.db import models
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
import uuid
# Create your models here.
class Cycle(models.Model):
    cycle_no = models.CharField(max_length=100,unique=True)
    controller_no = models.CharField(max_length=100,unique=True)

    def __str__(self):
        return self.cycle_no
    
class Participent(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True,null=True,)
    phone = models.CharField(max_length=30,blank=True,null=True,)
    profile = models.ImageField(upload_to='profile_images/', blank=True, null=True)
    registered_on = models.DateField(auto_now_add=True)

class ParticipentCycle(models.Model):
    participent = models.ForeignKey(Participent, on_delete=models.CASCADE)
    cycle = models.ForeignKey(Cycle, on_delete=models.CASCADE)
    active_participant = models.ForeignKey(
        Participent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_cycle_allocations",
    )
    power = models.FloatField(null=True, blank=True, default=0.0)
    voltage = models.FloatField(null=True, blank=True, default=0.0)
    other_participant = models.ManyToManyField(
        Participent,
        related_name='shared_cycles',
        blank=True,
        default=[],  
    )
    amperage = models.FloatField(null=True, blank=True, default=0.0)
    updated_at = models.DateTimeField(auto_now=True)
    total_power = models.FloatField(null=True, blank=True, default=0.0)
    total_voltage = models.FloatField(null=True, blank=True, default=0.0)
    total_amperage = models.FloatField(null=True, blank=True, default=0.0)
    duration = models.DurationField(null=True, blank=True, default=timedelta)
    def __str__(self):
        return f"{self.id}"

class PowerMonitor(models.Model):
    participent = models.ForeignKey(ParticipentCycle,on_delete=models.CASCADE)
    participant_data = models.ForeignKey(Participent,on_delete=models.CASCADE)
    current_power = models.FloatField(null=True, blank=True, default=0.0)
    current_voltage = models.FloatField(null=True, blank=True, default=0.0)
    current_amperage = models.FloatField(null=True, blank=True, default=0.0)
    updated_at = models.DateTimeField(auto_now=True)
    total_power = models.FloatField(null=True, blank=True, default=0.0)
    total_voltage = models.FloatField(null=True, blank=True, default=0.0)
    total_amperage = models.FloatField(null=True, blank=True, default=0.0)

class ActiveParticipent(models.Model):
    time_duration = models.TimeField()
    cycle = models.ManyToManyField(Cycle)
    is_auto_ranking = models.BooleanField(default=True)
    number_of_participant = models.IntegerField(default=4)
    leaderboard_sort = models.CharField(max_length=20, default="power")

class Grouping(models.Model):
    is_grouping = models.BooleanField(default=False)

    def __str__(self):
        return str(self.is_grouping)

class Group(models.Model):
    name = models.CharField(max_length=100)
    members = models.ManyToManyField(
        ParticipentCycle,
        related_name="groups"
    )

    def __str__(self):
        return self.name
    



"""
App theme model.

Mirrors the two color palettes in the frontend's theme.jsx:
  - COLORS (DEFAULT_COLORS) -> used by ranking/participant screens
  - THEME  (DEFAULT_THEME)  -> "Go Green" palette used by live power chart screens

Only colors are stored here (sizes/fonts stay static in the frontend,
per the frontend's mergeColors() design — see theme.jsx / SocketContext.jsx).

Typical flow:
  1. Admin edits the single active AppTheme row (Django admin, or your
     own settings screen) — e.g. changes `gold` or `neon`.
  2. On save, a signal (see bottom of this file) broadcasts the new
     palette to connected clients over the "screen" WebSocket group as
     a `theme_updated` message, so screens update live without reload.
  3. `AppTheme.get_active().to_payload()` is also what your
     `/api/get_active_theme/` endpoint should return, so a page
     refresh picks up the current palette immediately (see
     `currentTheme()` in SocketContext.jsx).
"""

from django.core.validators import RegexValidator
from django.db import models, transaction

# Accepts: #rgb, #rrggbb, rgb(...), rgba(...), linear-gradient(...),
# radial-gradient(...), or a small set of CSS color keywords (e.g. "gold").
# This is intentionally permissive — it exists to catch obvious typos/
# injection, not to be a full CSS parser.
COLOR_VALUE_VALIDATOR = RegexValidator(
    regex=r"^[a-zA-Z0-9#().,%\-\+\s]*$",
    message="Enter a valid CSS color/shadow value (letters, numbers, #, (), %, -, +, spaces, and commas only).",
)
 
 
def color_field(default, max_length=255):
    """Shortcut for a CharField that stores a CSS color/gradient value."""
    return models.CharField(
        max_length=max_length,
        default=default,
        validators=[COLOR_VALUE_VALIDATOR],
    )
 
 
class AppTheme(models.Model):
    """
    Singleton-style model: only one row should be marked is_active=True
    at a time. Use AppTheme.get_active() to fetch it (falls back to
    creating a default row if none exists yet).
    """
 
    name = models.CharField(
        max_length=100,
        default="Default",
        help_text="Internal label for this theme preset (e.g. 'Diwali 2026', 'Default Go Green').",
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Only one theme can be active at a time. Activating this one deactivates all others.",
    )
 
    # ---------------------------------------------------------------
    # COLORS palette (ranking / participant screens)
    # Field names + defaults mirror DEFAULT_COLORS in theme.jsx exactly.
    # ---------------------------------------------------------------
    colors_background_gradient = color_field(
        "radial-gradient(circle at 50% 25%, #1e5a35 0%, #0c2818 45%, #030a06 100%)"
    )
    colors_header_border = color_field("#22c55e", max_length=50)
    colors_header_border_shadow = color_field("rgba(41, 235, 112, 0.55)", max_length=60)
    colors_white = color_field("#ffffff", max_length=50)
    colors_green = color_field("#4ade80", max_length=50)
    colors_gold = color_field("#e1ba2d", max_length=50)
    colors_highlight_border = color_field("#e9ff3f", max_length=50)
    colors_highlight_shadow = color_field("rgba(233,255,63,0.4)", max_length=60)
    colors_normal_row_border = color_field("rgba(255,255,255,0.75)", max_length=60)
    colors_circle_bg = color_field("#04140a", max_length=50)
    colors_circle_highlight_border = color_field("#d4ff3f", max_length=50)
    colors_circle_highlight_shadow = color_field("rgba(212,255,63,0.65)", max_length=60)
 
    # ---------------------------------------------------------------
    # THEME palette ("Go Green" — live power chart screens)
    # Field names + defaults mirror DEFAULT_THEME in theme.jsx exactly.
    # ---------------------------------------------------------------
    theme_bg = color_field("#04140A", max_length=50)
    theme_bg_gradient = color_field(
        "radial-gradient(circle at 10% -10%, rgba(0,255,140,0.14), transparent 45%), "
        "radial-gradient(circle at 90% 110%, rgba(0,255,140,0.08), transparent 45%)"
    )
    theme_panel = color_field("#0B2013", max_length=50)
    theme_panel_border = color_field("rgba(0,255,140,0.28)", max_length=60)
    theme_panel_glow = color_field(
        "0 0 0 1px rgba(0,255,140,0.15), 0 8px 28px rgba(0,0,0,0.45)"
    )
    theme_neon = color_field("#39FF88", max_length=50)
    theme_neon_soft = color_field("rgba(57,255,136,0.14)", max_length=60)
    theme_gold = color_field("#FFE566", max_length=50)
    theme_text = color_field("#F2FFF6", max_length=50)
    theme_subtext = color_field("#7FDDA0", max_length=50)
    theme_muted = color_field("#4E7A5E", max_length=50)
    theme_divider = color_field("#123319", max_length=50)
    font_family = models.CharField(
        max_length=120,
        default="'Poppins', sans-serif",
        help_text="CSS font-family stack applied app-wide, e.g. \"'Inter', sans-serif\".",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name = "App Theme"
        verbose_name_plural = "App Themes"
        ordering = ["-updated_at"]
 
    def __str__(self):
        return f"{self.name} {'(active)' if self.is_active else ''}".strip()
 
    # ------------------------------------------------------------
    # Save / activation handling
    # ------------------------------------------------------------
    def save(self, *args, **kwargs):
        """
        Enforce single active theme atomically: if this row is being
        saved as active, deactivate every other row in the same
        transaction so we never end up with two active rows or a
        half-applied state if something fails mid-save.
        """
        if self.is_active:
            with transaction.atomic():
                AppTheme.objects.exclude(pk=self.pk).update(is_active=False)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
 
    # ------------------------------------------------------------
    # Payload helpers
    # ------------------------------------------------------------
    def to_payload(self):
        """
        Returns the exact shape mergeColors() / theme_updated expects
        on the frontend:
            { "colors": {...}, "theme": {...} }
        Only keys that differ from frontend defaults NEED to be sent,
        but sending the full palette is simplest and always correct
        since mergeColors() just overwrites matching keys anyway.
        """
        return {
            "colors": {
                "backgroundGradient": self.colors_background_gradient,
                "headerBorder": self.colors_header_border,
                "headerBorderShadow": self.colors_header_border_shadow,
                "white": self.colors_white,
                "green": self.colors_green,
                "gold": self.colors_gold,
                "highlightBorder": self.colors_highlight_border,
                "highlightShadow": self.colors_highlight_shadow,
                "normalRowBorder": self.colors_normal_row_border,
                "circleBg": self.colors_circle_bg,
                "circleHighlightBorder": self.colors_circle_highlight_border,
                "circleHighlightShadow": self.colors_circle_highlight_shadow,
            },
            "theme": {
                "bg": self.theme_bg,
                "bgGradient": self.theme_bg_gradient,
                "panel": self.theme_panel,
                "panelBorder": self.theme_panel_border,
                "panelGlow": self.theme_panel_glow,
                "neon": self.theme_neon,
                "neonSoft": self.theme_neon_soft,
                "gold": self.theme_gold,
                "text": self.theme_text,
                "subtext": self.theme_subtext,
                "muted": self.theme_muted,
                "divider": self.theme_divider,
            },
            "fontFamily": self.font_family,   # NEW — this is what was missing end-to-end

        }
 
    @classmethod
    def get_active(cls):
        """
        Returns the current active theme, creating a default one
        (all field defaults, is_active=True) if none exists yet.
        """
        active = cls.objects.first()
        if active:
            return active
        # No active theme yet — create one from field defaults.
        return cls.objects.create(name="Default", is_active=True)
 
 
# ---------------------------------------------------------------------
# Broadcast theme changes live over the "screen" WS group whenever the
# active theme is saved AND its payload actually changed, so connected
# clients update without needing a page refresh — without spamming a
# broadcast on every no-op save (e.g. touching `name` only).
#
# Wire this up in apps.py's ready() if you want it, e.g.:
#
#   # apps.py
#   class YourAppConfig(AppConfig):
#       def ready(self):
#           import yourapp.models  # noqa: triggers the signal below
#
# Requires channels + a "screen" group that ws/screen/client/ consumers
# already join (matching the group your screen_changed / free_text_updated
# messages are broadcast to).
# ---------------------------------------------------------------------
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
 
 
@receiver(pre_save, sender=AppTheme)
def _stash_previous_payload(sender, instance, **kwargs):
    """
    Stash the pre-save payload on the instance so post_save can diff
    against it and skip broadcasting when nothing visible changed.
    """
    if not instance.pk:
        instance._previous_payload = None
        return
    try:
        previous = AppTheme.objects.get(pk=instance.pk)
        instance._previous_payload = previous.to_payload()
    except AppTheme.DoesNotExist:
        instance._previous_payload = None
 
 
@receiver(post_save, sender=AppTheme)
def broadcast_theme_update(sender, instance, **kwargs):
    if not instance.is_active:
        return
 
    new_payload = instance.to_payload()
    if getattr(instance, "_previous_payload", None) == new_payload:
        # No visible color change (e.g. only `name` was edited) — skip
        # the broadcast to avoid unnecessary WebSocket traffic.
        return
 
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
 
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
 
        async_to_sync(channel_layer.group_send)(
            "screen",  # must match the group name your consumer adds clients to
            {
                "type": "theme_update",  # must match a handler method on your consumer, e.g. theme_update()
                "message": {
                    "type": "theme_updated",
                    "data": new_payload,
                },
            },
        )
    except Exception:
        # Never let a broadcast failure break saving the theme in
        # admin — worst case, clients pick it up on next refresh via
        # /api/get_active_theme/.
        pass


class ParticipantCyclingDuration(models.Model):
    participant = models.ForeignKey(Participent,on_delete=models.CASCADE)
    start_at = models.DateTimeField(auto_now_add=True)
    end_at = models.DateTimeField(null = True,blank=True)
    is_ended = models.BooleanField(default=False)


class CycleRideSession(models.Model):
    """
    Represents one participant's complete riding session on a cycle.

    A session can contain multiple riding segments because the participant
    may pause/break and resume later.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    cycle = models.ForeignKey(
        Cycle,
        on_delete=models.CASCADE,
        related_name="ride_sessions",
    )

    participant = models.ForeignKey(
        Participent,
        on_delete=models.CASCADE,
        related_name="cycle_ride_sessions",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=False)
    is_paused = models.BooleanField(default=False)
    is_ended = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Optional session time limit.
    # None = unlimited session.
    session_limit_seconds = models.PositiveIntegerField(null = True, blank=True)

    class Meta:
        ordering = ["started_at", "created_at"]

    def __str__(self):
        return f"{self.cycle.cycle_no} - {self.participant.name}"


class CycleRideSegment(models.Model):
    """
    One actual riding interval inside a CycleRideSession.

    Example:

        10:00 -> 10:30
        10:45 -> 11:10

    These two segments belong to the same session if the participant
    paused and later resumed.
    """

    id = models.BigAutoField(primary_key=True)

    session = models.ForeignKey(
        CycleRideSession,
        on_delete=models.CASCADE,
        related_name="segments",
    )

    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=False)

    # Snapshot/aggregated values for this riding segment.
    total_power = models.FloatField(
        null=True,
        blank=True,
        default=0.0,
    )

    total_voltage = models.FloatField(
        null=True,
        blank=True,
        default=0.0,
    )

    average_power = models.FloatField(
        null=True,
        blank=True,
        default=0.0,
    )

    average_voltage = models.FloatField(
        null=True,
        blank=True,
        default=0.0,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["started_at"]

    def __str__(self):
        return (
            f"{self.session.participant.name} - "
            f"{self.started_at}"
        )

class AppTitle(models.Model):
    title = models.CharField(max_length=40, default="Go Green")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class AnimationDuration(models.Model):
    duration_seconds = models.IntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)


