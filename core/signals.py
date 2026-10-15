from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PowerMonitor, ParticipentCycle

# Any gap between consecutive readings larger than this is treated as the
# participant having stopped/disconnected rather than continuously cycling
# (e.g. app was closed, controller lost power) — so it isn't counted toward
# duration. Tune to match your expected reading cadence; PowerMonitorConsumer
# polls every 5s, so readings should normally be close together.
MAX_GAP_SECONDS = 30


@receiver(post_save, sender=PowerMonitor)
def accumulate_duration(sender, instance, created, **kwargs):
    if not created:
        return

    participant_cycle_id = instance.participent_id

    # The previous reading for this same participant/cycle, if any —
    # excludes the row we just created.
    previous = (
        PowerMonitor.objects
        .filter(participent_id=participant_cycle_id)
        .exclude(pk=instance.pk)
        .order_by("-updated_at")
        .first()
    )

    if previous is None:
        return  # first reading for this cycle — nothing to add yet

    gap = instance.updated_at - previous.updated_at
    if gap.total_seconds() <= 0 or gap.total_seconds() > MAX_GAP_SECONDS:
        return  # clock skew, duplicate timestamp, or a stale/disconnected gap

    ParticipentCycle.objects.filter(pk=participant_cycle_id).update(
        duration=F("duration") + gap
    )