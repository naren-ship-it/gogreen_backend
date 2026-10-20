from asgiref.sync import sync_to_async
from django.db.models import F


@sync_to_async
def save_monitor_data(data):
    from core.models import ParticipentCycle, PowerMonitor, Cycle,ParticipantCyclingDuration

    controller_no = data.get("controller_no")

    try:
        cycle = Cycle.objects.get(controller_no=controller_no)
        allocation = ParticipentCycle.objects.get(cycle=cycle)
    except (Cycle.DoesNotExist, ParticipentCycle.DoesNotExist):
        print(f"Cycle/allocation not found for controller_no={controller_no}")
        return

    current_voltage = float(data.get("voltage", 0.0))
    current_amperage = float(data.get("amperage", 0.0))
    current_power = float(data.get("power", 0.0))

    allocation.voltage = current_voltage
    allocation.amperage = current_amperage
    allocation.power = current_power

    allocation.total_voltage = F("total_voltage") + current_voltage
    allocation.total_amperage = F("total_amperage") + current_amperage
    allocation.total_power = F("total_power") + current_power

    allocation.save()
    allocation.refresh_from_db()
    participant_cycling = (
        ParticipantCyclingDuration.objects
        .filter(participant=allocation.participent)
        .order_by("-start_at")
        .first()
    )

    if participant_cycling is None or participant_cycling.is_ended:
        ParticipantCyclingDuration.objects.create(
            participant=allocation.participent,
            is_ended=False
        )

    PowerMonitor.objects.create(
        participent=allocation,
        participant_data = allocation.participent,
        current_power=current_power,
        current_voltage=current_voltage,
        current_amperage=current_amperage,
        total_power=allocation.total_power,
        total_voltage=allocation.total_voltage,
        total_amperage=allocation.total_amperage,
    )