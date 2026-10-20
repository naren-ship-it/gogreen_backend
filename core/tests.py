from django.core.cache import cache
from django.test import TestCase, override_settings

from .cache_utils import get_dashboard_context, invalidate_dashboard_cache


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
)
class CacheUtilsTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_dashboard_context_is_cached_and_can_be_invalidated(self):
        context = get_dashboard_context()

        self.assertIn("cycles", context)
        self.assertEqual(context, cache.get("dashboard_context_v1"))

        invalidate_dashboard_cache()

        self.assertIsNone(cache.get("dashboard_context_v1"))
