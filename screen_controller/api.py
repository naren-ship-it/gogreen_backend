from rest_framework.decorators import APIView
from rest_framework.response import Response
from rest_framework import status
from utils.close_receiver import close_window_by_pid
from .models import *
from .serializer import *
from core.models import  *
from rest_framework.permissions import AllowAny
from django.forms import ValidationError
from django.template.context_processors import request


class WindoePositionalAPI(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 
    def get(self,request):
        
        try:
            data = ScreenPosition.objects.first()
            serializers = ScreenPositionSerializer(data,many=False)
            return Response(serializers.data,status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response(str(e),status=status.HTTP_404_NOT_FOUND)


class ParticipentCycleAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 
    def get(self,request):
        try:
            response = []
            data = ParticipentCycle.objects.all()
            for d in data:
                response.append({
                    'id':d.id,
                    'name':d.participent.name,
                    'cycle':d.cycle.cycle_no,
                    'cycle_id':d.cycle.pk,
                })
                
            return Response(response,status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response(str(e),status=status.HTTP_404_NOT_FOUND)


class SelectedCyclesAPI(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 

    def get(self, request):
        try:
            data = ActiveParticipent.objects.order_by("-id").first()
            if data is None:
                return Response({"duration": 0, "cycles": []}, status=status.HTTP_200_OK)
            
            duration_minutes = (
                data.time_duration.hour * 60
                + data.time_duration.minute
                + data.time_duration.second // 60
            )
    
            response = {
                "duration": duration_minutes,
                "cycles": list(data.cycle.values_list("pk", flat=True)),
                "leaderboard_sort": data.leaderboard_sort,
            }
    
            return Response(response, status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response(str(e), status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        try:
            cycles = request.data.get("cycles", [])
            if not cycles:
                return Response({"error": "cycles is required"}, status=status.HTTP_400_BAD_REQUEST)

            cycle_nos = [str(c) for c in cycles]
            matched = Cycle.objects.filter(cycle_no__in=cycle_nos)
            if not matched.exists():
                return Response({"error": f"No cycles found for: {cycle_nos}"}, status=status.HTTP_404_NOT_FOUND)

            active = ActiveParticipent.objects.order_by("-id").first()
            if active is None:
                return Response({"error": "ActiveParticipent not configured"}, status=status.HTTP_404_NOT_FOUND)

            active.cycle.set(matched)
            return Response({"cycles": list(matched.values_list("cycle_no", flat=True))}, status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        
        
        
        
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.core.exceptions import ValidationError as DjangoValidationError

from .models import Windows
from .serializer import WindowsSerializer


class WindowsAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    # GET: List all windows or retrieve a specific window
    def get(self, request, pk=None):
        print("[DEBUG] WindowsAPIView GET called")

        # Fetch a single window by ID
        if pk is not None:
            print(f"[DEBUG] Fetching window ID: {pk}")

            try:
                window = Windows.objects.select_related(
                    "position",
                    "activee_screen",
                ).get(pk=pk)

                print(f"[DEBUG] Window found: {window.name}")

                return Response(
                    WindowsSerializer(window).data,
                    status=status.HTTP_200_OK,
                )

            except Windows.DoesNotExist:
                return Response(
                    {"error": "Window not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # Fetch all windows for admin, or active windows for clients
        windows = Windows.objects.select_related(
            "position",
            "activee_screen",
        )

        role = request.query_params.get("role")
        print(f"[DEBUG] Role from query params: {role}")
        if role != "admin":
            windows = windows.filter(is_active=True)

        windows = windows.order_by("id")

        print(f"[DEBUG] Total windows: {windows.count()}")

        return Response(
            WindowsSerializer(windows, many=True).data,
            status=status.HTTP_200_OK,
        )

    # POST: Create a screen position and its window together
    def post(self, request):
        print("[DEBUG] WindowsAPIView POST called")
        print(f"[DEBUG] Request data: {request.data}")

        window_name = request.data.get("name")
        screen_id = request.data.get("activee_screen")
        position_data = request.data.get("position_details")

        # Validate window name.
        if not isinstance(window_name, str) or not window_name.strip():
            return Response(
                {"name": "A valid window name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate position data.
        if not isinstance(position_data, dict):
            return Response(
                {"position_details": "Position settings must be an object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Find the existing screen.
        try:
            screen = Screen.objects.get(pk=screen_id)
        except (Screen.DoesNotExist, ValueError, TypeError):
            return Response(
                {"activee_screen": "Invalid screen ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
            
        # Block creating a new window if this screen already has one
        # with a live client process attached (pid != 0).
        existing_active = (
            Windows.objects
            .select_related("position", "activee_screen")
            .filter(activee_screen_id=screen.pk)
            .exclude(pid=0)
            .first()
        )
        if existing_active is not None:
            return Response(
                {
                    "error": (
                        f"Screen '{screen.name}' already has an active "
                        f"window (window_id={existing_active.pk}, "
                        f"pid={existing_active.pid}). Close it before "
                        "creating a new one."
                    ),
                    "existing_window": {
                        "id": existing_active.pk,
                        "name": existing_active.name,
                        "pid": existing_active.pid,
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )

        allowed_position_fields = {
            "name",
            "x",
            "y",
            "width",
            "height",
            "fullscreen",
            "always_on_top",
            "resizable",
            "movable",
            "minimizable",
            "maximizable",
            "visible",
            "menu_bar_visible",
            "auto_hide_menu_bar",
            "opacity",
        }

        position_data = {
            key: value
            for key, value in position_data.items()
            if key in allowed_position_fields
        }

        position_data.setdefault("name", window_name)

        try:
            with transaction.atomic():

                # STEP 1: Create ScreenPosition directly using the model.
                position = ScreenPosition.objects.create(**position_data)

                print(
                    f"[DEBUG] ScreenPosition created: ID={position.pk}"
                )

                # STEP 2: Allocate that position to the new window.
                is_active = request.data.get("is_active", True)

                if not isinstance(is_active, bool):
                    raise ValueError("is_active must be true or false.")

                window = Windows.objects.create(
                    name=window_name.strip(),
                    position=position,
                    activee_screen=screen,
                    is_active=is_active,
                )

                print(
                    f"[DEBUG] Window created: ID={window.pk}, "
                    f"Name={window.name}, "
                    f"Position ID={window.position_id}, "
                    f"Screen ID={window.activee_screen_id}"
                )

            # STEP 3: Build the response without using a serializer.
            return Response(
                {
                    "id": window.pk,
                    "name": window.name,
                    "position": position.pk,
                    "activee_screen": screen.pk,
                    "is_active": window.is_active,
                    "position_details": {
                        "id": position.pk,
                        "name": position.name,
                        "x": position.x,
                        "y": position.y,
                        "width": position.width,
                        "height": position.height,
                        "fullscreen": position.fullscreen,
                        "always_on_top": position.always_on_top,
                        "resizable": position.resizable,
                        "movable": position.movable,
                        "minimizable": position.minimizable,
                        "maximizable": position.maximizable,
                        "visible": position.visible,
                        "menu_bar_visible": position.menu_bar_visible,
                        "auto_hide_menu_bar": position.auto_hide_menu_bar,
                        "opacity": position.opacity,
                    },
                    "active_screen_details": {
                        "id": screen.pk,
                        "name": screen.name,
                        "path": screen.path,
                        "thumbnail": (
                            screen.thumbnail.url
                            if screen.thumbnail
                            else None
                        ),
                        "is_live": screen.is_live,
                    },
                },
                status=status.HTTP_201_CREATED,
            )

        except (ValidationError, ValueError, TypeError) as exc:
            print(f"[DEBUG] Creation failed: {exc}")

            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
    # PATCH: Update selected window fields
    def patch(self, request, pk):
        print(f"[DEBUG] WindowsAPIView PATCH called for ID: {pk}")

        try:
            window = Windows.objects.select_related(
                "position",
                "activee_screen",
            ).get(pk=pk)
        except Windows.DoesNotExist:
            return Response(
                {"error": "Window not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = WindowsSerializer(
            window,
            data=request.data,
            partial=True,
        )

        if serializer.is_valid():
            updated_window = serializer.save()

            return Response(
                WindowsSerializer(updated_window).data,
                status=status.HTTP_200_OK,
            )

        print(f"[DEBUG] Validation errors: {serializer.errors}")

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    # DELETE: Delete a window

    def delete(self, request, pk):
        print(f"[DEBUG] WindowsAPIView DELETE called for ID: {pk}")

        try:
            window = Windows.objects.get(pk=pk)
        except Windows.DoesNotExist:
            return Response(
                {"error": "Window not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        window_name = window.name
        window_id = window.pk
        pid = window.pid

        close_result = None

        # If this window has a live process attached, try to close it
        # before removing the DB record, so the screen doesn't end up
        # with an orphaned app still open.
        if pid:
            close_result = close_window_by_pid(pid)
            print(
                f"[DEBUG] close_window_by_pid({pid}) -> {close_result}"
            )

            if not close_result["success"]:
                # Process couldn't be closed cleanly. Still proceed with
                # deleting the DB record, but let the caller know the
                # app may still be running on screen.
                print(
                    f"[DEBUG] Window {window_id} deleted but process "
                    f"{pid} close failed: {close_result['message']}"
                )

        window.delete()

        print(
            "[DEBUG] Window deleted successfully: "
            f"ID={window_id}, Name={window_name}, pid={pid}"
        )

        response_data = {"message": "Window deleted successfully"}

        if close_result is not None:
            response_data["process_close"] = close_result

        return Response(response_data, status=status.HTTP_200_OK)
        
