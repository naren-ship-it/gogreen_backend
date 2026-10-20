import random

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import *
from screen_controller.models import Screen
from screen_controller.serializer import ScreenSerializer

from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny


class LastScreenAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 
    def get(self,request):
        try:
            screen = Screen.objects.get(is_live=True)
            serializer = ScreenSerializer(screen)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Screen.DoesNotExist:
            return Response({"error": "No live screen found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UpdateReadingAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 
    def get(self,request):
        return Response("Hello")
    def post(self, request):
        print(request.data)
        controller_id = request.data.get("controller_id")
        voltage = request.data.get("voltage")
        amperage = request.data.get("amperage")
        power = request.data.get("power")

        try:
            cycle = Cycle.objects.get(controller_no = controller_id)
            allocation = ParticipentCycle.objects.get(cycle=cycle)

            # convert to floats (protect against None/string)
            current_voltage = float(voltage or 0.0)
            current_amperage = float(amperage or 0.0)
            current_power = float(power or 0.0)

            # latest readings
            allocation.voltage = current_voltage
            allocation.amperage = current_amperage
            allocation.power = current_power

            # accumulate totals in DB:
            # total_x = total_x + current_x
            allocation.total_voltage = F('total_voltage') + current_voltage
            allocation.total_amperage = F('total_amperage') + current_amperage
            allocation.total_power = F('total_power') + current_power

            allocation.save()

            # reload actual numeric totals after F() updates
            allocation.refresh_from_db()  # [web:36][web:44][web:47]
            try:
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
                from core.models import CycleRideSession
                active_session = (
                    CycleRideSession.objects
                    .filter(
                        cycle=cycle,
                        is_active=True,
                        is_ended=False,
                    )
                    .select_related("participant")
                    .order_by("-created_at")
                    .first()
                )
                participant_data = (
                    active_session.participant
                    if active_session
                    else allocation.participent
                )
                power_monitor = PowerMonitor.objects.create(
                    participent = allocation,
                    participant_data = participant_data,
                    current_power = current_power,
                    current_voltage = current_voltage,
                    current_amperage = current_amperage,
                    total_power = allocation.total_power,
                    total_voltage = allocation.total_voltage,
                    total_amperage =  allocation.total_amperage
                    )
            except Exception as e:
                print(e)

            return Response(
                {
                    "status": "success",
                    "cycle": allocation.cycle.cycle_no,
                    "voltage": allocation.voltage,           # latest voltage
                    "amperage": allocation.amperage,         # latest amp
                    "power": allocation.power,               # latest power
                    "total_voltage": allocation.total_voltage,
                    "total_amperage": allocation.total_amperage,
                    "total_power": allocation.total_power,
                },
                status=status.HTTP_200_OK,
            )

        except ParticipentCycle.DoesNotExist:
            return Response(
                {
                    "status": "error",
                    "message": "Allocation not found."
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        

class GroupingAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 
    def get(self,request):
        try:
            grouping = Grouping.objects.first()
            if grouping:
                return Response({"is_grouping": grouping.is_grouping}, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Grouping not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GroupAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def _serialize_group(self, group):
        return {
            "id": group.id,
            "name": group.name,
            "members": [
                {
                    "id": member.id,
                    "participent_name": member.participent.name,
                    "cycle_no": member.cycle.cycle_no,
                    "controller_no": member.cycle.controller_no,
                    "voltage": member.voltage,
                    "amperage": member.amperage,
                    "power": member.power,
                }
                for member in group.members.all()
            ],
        }

    def get(self, request):
        group_id = request.query_params.get("group_id")
        try:
            if group_id:
                group = get_object_or_404(Group, pk=group_id)
                return Response(self._serialize_group(group), status=status.HTTP_200_OK)

            groups = Group.objects.all()
            return Response([
                self._serialize_group(group) for group in groups
            ], status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        group_id = request.data.get("group_id")
        name = request.data.get("name")
        cycle_id = request.data.get("cycle_id")
        member_ids = request.data.get("member_ids")
        target_group_id = request.data.get("target_group_id")
        remove_member_id = request.data.get("remove_member_id")

        try:
            if group_id:
                group = get_object_or_404(Group, pk=group_id)
                if name:
                    group.name = name
                    group.save()
            else:
                if not name:
                    return Response({"error": "Group name is required when creating a new group."}, status=status.HTTP_400_BAD_REQUEST)
                group = Group.objects.create(name=name)

            if target_group_id is not None and cycle_id is not None:
                target_group = get_object_or_404(Group, pk=target_group_id)
                member = get_object_or_404(ParticipentCycle, pk=cycle_id)
                group.members.remove(member)
                target_group.members.add(member)
                return Response({
                    "status": "member_moved",
                    "from_group": self._serialize_group(group),
                    "to_group": self._serialize_group(target_group),
                }, status=status.HTTP_200_OK)

            if member_ids is not None:
                if not isinstance(member_ids, list):
                    return Response({"error": "member_ids must be a list."}, status=status.HTTP_400_BAD_REQUEST)
                members = ParticipentCycle.objects.filter(pk__in=member_ids)
                group.members.set(members)
            elif remove_member_id is not None:
                member = get_object_or_404(ParticipentCycle, pk=remove_member_id)
                group.members.remove(member)
            elif cycle_id is not None:
                member = get_object_or_404(ParticipentCycle, pk=cycle_id)
                group.members.add(member)

            return Response(self._serialize_group(group), status=status.HTTP_200_OK)
        except ParticipentCycle.DoesNotExist:
            return Response({"error": "ParticipentCycle not found."}, status=status.HTTP_404_NOT_FOUND)
        except Group.DoesNotExist:
            return Response({"error": "Group not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request):
        group_id = request.data.get("group_id") or request.query_params.get("group_id")
        cycle_id = request.data.get("cycle_id") or request.query_params.get("cycle_id")

        if not group_id:
            return Response({"error": "group_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            group = get_object_or_404(Group, pk=group_id)
            if cycle_id is not None:
                member = get_object_or_404(ParticipentCycle, pk=cycle_id)
                group.members.remove(member)
                return Response({"status": "member_removed", "group_id": group.id}, status=status.HTTP_200_OK)

            group.delete()
            return Response({"status": "group_deleted", "group_id": int(group_id)}, status=status.HTTP_200_OK)
        except ParticipentCycle.DoesNotExist:
            return Response({"error": "ParticipentCycle not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class ParticipantAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            participants = (
                ParticipentCycle.objects
                .select_related("participent", "cycle")
                .values(
                    "cycle__cycle_no",
                    "cycle__controller_no",
                    "participent__name",
                    "participent__profile",
                    "participent__registered_on",
                    "participent__id",
                )
            )

            data = []

            for participant in participants:

                profile = participant["participent__profile"]

                # Generate complete image URL
                if profile:
                    profile_url = request.build_absolute_uri(
                        f"/media/{profile}"
                    )
                else:
                    profile_url = None

                data.append({
                    "participent_id": participant["participent__id"],
                    "cycle_no": participant["cycle__cycle_no"],
                    "controller_no": participant["cycle__controller_no"],
                    "participant_name": participant["participent__name"],
                    "participant_profile": profile_url,
                    "participant_registered_on": participant[
                        "participent__registered_on"
                    ],
                })

            return Response({
                "status": True,
                "message": "Successfully fetched the data",
                "data": data,
            })

        except Exception as e:
            return Response({
                "status": False,
                "message": str(e),
            })
            
            
            

from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET


LOG_FILE = Path(settings.BASE_DIR) / "backend-terminal.log"


@require_GET
def backend_terminal_logs(request):
    if not LOG_FILE.is_file():
        return JsonResponse({
            "lines": [],
            "error": "Log file not found. Start Uvicorn using the PowerShell launcher.",
        })

    try:
        with LOG_FILE.open("r", encoding="utf-8", errors="replace") as file:
            lines = file.readlines()

        return JsonResponse({
            "lines": [line.rstrip("\r\n") for line in lines[-500:]],
        })
    except OSError:
        return JsonResponse({
            "lines": [],
            "error": "Unable to read backend log file.",
        }, status=500)
