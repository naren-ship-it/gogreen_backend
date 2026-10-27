from django.apps import apps
from django.contrib import admin

from .models import *
from screen_controller.models import *


@admin.register(Cycle)
class CycleAdmin(admin.ModelAdmin):
    list_display = ('cycle_no', 'controller_no')


@admin.register(Participent)
class ParticipentAdmin(admin.ModelAdmin):
    list_display = ('name', 'registered_on')


@admin.register(ParticipentCycle)
class ParticipentCycleAdmin(admin.ModelAdmin):
    list_display = ('participent', 'cycle', 'voltage', 'amperage')


@admin.register(Grouping)
class GroupingAdmin(admin.ModelAdmin):
    list_display = ('id', 'is_grouping')

@admin.register(ParticipantCyclingDuration)
class ParticipantCyclingDurationAdmin(admin.ModelAdmin):
    list_display = ['participant','start_at','end_at','is_ended']
admin.site.register(PowerMonitor)
# Everything above got a hand-picked ModelAdmin. Everything else in every
# installed app gets auto-registered below with the default admin, so new
# models show up without needing an admin.py edit each time.
import importlib

for app_config in apps.get_app_configs():
    # If this app ships its own admin.py, let Django's normal admin
    # autodiscovery import and run it as usual — don't pre-register its
    # models ourselves, or we race with (and break) that file's own
    # admin.site.register() calls (e.g. rest_framework_simplejwt's
    # token_blacklist).
    try:
        importlib.import_module(f'{app_config.name}.admin')
        has_own_admin = True
    except ModuleNotFoundError:
        has_own_admin = False

    if has_own_admin:
        continue

    for model in app_config.get_models():
        if admin.site.is_registered(model):
            continue
        try:
            admin.site.register(model)
        except admin.sites.AlreadyRegistered:
            pass


admin.site.register(AnimationDuration)
admin.site.register(DCModbusReadControl)