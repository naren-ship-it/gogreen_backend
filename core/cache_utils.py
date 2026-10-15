from django.core.cache import cache

from .models import Cycle, Participent, ParticipentCycle


DASHBOARD_CACHE_KEY = "dashboard_context_v1"


def get_dashboard_context():
    cached = cache.get(DASHBOARD_CACHE_KEY)
    if cached is not None:
        return cached

    context = {
        "cycles": list(Cycle.objects.all()),
        "participants": list(Participent.objects.all()),
        "allocations": list(ParticipentCycle.objects.all()),
    }
    cache.set(DASHBOARD_CACHE_KEY, context, 60)
    return context


def invalidate_dashboard_cache():
    cache.delete(DASHBOARD_CACHE_KEY)
