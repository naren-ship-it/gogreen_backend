from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Avg, F, Max
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from admin_panel.models import FreeText, FreeTextDraft

from core.models import *

from screen_controller.models import Screen
from screen_controller.serializer import *  # noqa: F401,F403
from .serializer import *  # noqa: F401,F403


# ================================================================
# CYCLE HISTORY HELPERS
# ================================================================

# def expire_cycle_ride_session(session, now=None):
#     """
#     Automatically ends an active ride session when its configured
#     active-riding duration reaches the session limit.

#     IMPORTANT:
#     - Only ACTIVE riding time is counted.
#     - PAUSE time is NOT counted.
#     - Meter collection is NOT affected.
#     - The segment/session is ended at the EXACT expiry timestamp.
#     """

#     now = now or timezone.now()

#     # Unlimited session or already stopped.
#     if (
#         session.is_ended
#         or not session.is_active
#         or session.session_limit_seconds is None
#     ):
#         return False

#     segments = list(
#         CycleRideSegment.objects
#         .filter(session=session)
#         .order_by("started_at", "id")
#     )

#     if not segments:
#         return False

#     limit_seconds = float(session.session_limit_seconds)

#     elapsed_closed_seconds = 0.0
#     active_segment = None

#     # ------------------------------------------------------------
#     # Calculate already-completed riding time.
#     # ------------------------------------------------------------

#     for segment in segments:

#         if segment.ended_at is not None:

#             segment_seconds = max(
#                 0,
#                 (
#                     segment.ended_at
#                     - segment.started_at
#                 ).total_seconds(),
#             )

#             elapsed_closed_seconds += segment_seconds

#         elif segment.is_active:

#             active_segment = segment

#     # No active segment currently running.
#     if active_segment is None:
#         return False

#     # ------------------------------------------------------------
#     # How much active riding time remains?
#     # ------------------------------------------------------------

#     remaining_seconds = (
#         limit_seconds
#         - elapsed_closed_seconds
#     )

#     # The limit has already been consumed by previous segments.
#     if remaining_seconds <= 0:

#         expiry_at = active_segment.started_at

#     else:

#         expiry_at = (
#             active_segment.started_at
#             + timedelta(seconds=remaining_seconds)
#         )

#         # Not expired yet.
#         if now < expiry_at:
#             return False

#     # ------------------------------------------------------------
#     # Close active segment at exact expiry time.
#     # ------------------------------------------------------------

#     active_segment.ended_at = expiry_at
#     active_segment.is_active = False

#     active_segment.save(
#         update_fields=[
#             "ended_at",
#             "is_active",
#             "updated_at",
#         ]
#     )

#     # ------------------------------------------------------------
#     # End session.
#     # ------------------------------------------------------------

#     session.ended_at = expiry_at
#     session.is_active = False
#     session.is_paused = False
#     session.is_ended = True

#     session.save(
#         update_fields=[
#             "ended_at",
#             "is_active",
#             "is_paused",
#             "is_ended",
#             "updated_at",
#         ]
#     )

#     return True


def _get_session_elapsed_seconds(session, now=None):
    """
    Returns the actual ACTIVE riding duration of a session.

    PAUSE time is excluded.

    If the session currently has an active segment, that segment
    is counted up to `now`.

    IMPORTANT:
    This function only calculates duration.
    It never changes or ends the session.
    """

    now = now or timezone.now()

    used_seconds = 0.0

    segments = (
        CycleRideSegment.objects
        .filter(session=session)
        .order_by("started_at", "id")
    )

    for segment in segments:

        if segment.ended_at is not None:

            used_seconds += max(
                0,
                (
                    segment.ended_at
                    - segment.started_at
                ).total_seconds(),
            )

        elif segment.is_active:

            used_seconds += max(
                0,
                (
                    now
                    - segment.started_at
                ).total_seconds(),
            )

    return round(
        used_seconds,
        2,
    )


def session_limit_reached(session, now=None):
    """
    Returns True when the configured target duration has been reached.

    IMPORTANT:
    This does NOT end the session.

    A session can therefore be:

        is_active = True
        is_ended = False
        remaining_seconds = 0
        limit_reached = True

    That means:
        "Target reached, but participant is still riding."
    """

    if session.session_limit_seconds is None:
        return False

    elapsed_seconds = _get_session_elapsed_seconds(
        session,
        now=now,
    )

    return (
        elapsed_seconds
        >= float(session.session_limit_seconds)
    )


def close_open_cycle_ride_session(cycle, now=None):
    now = now or timezone.now()

    sessions = (
        CycleRideSession.objects
        .select_for_update()
        .filter(
            cycle=cycle,
            is_ended=False,
        )
        .order_by("created_at")
    )

    last_closed = None

    for session in sessions:

        _close_active_segment(
            session,
            now,
        )

        session.ended_at = now
        session.is_active = False
        session.is_paused = False
        session.is_ended = True

        session.save(
            update_fields=[
                "ended_at",
                "is_active",
                "is_paused",
                "is_ended",
                "updated_at",
            ]
        )

        last_closed = session

    return last_closed

def _num(value, digits=2):
    """
    None-safe rounding that also handles Decimal values.
    """
    return (
        round(float(value), digits)
        if value is not None
        else 0
    )


def _close_active_segment(session, now=None):
    now = now or timezone.now()

    segment = (
        CycleRideSegment.objects
        .filter(
            session=session,
            is_active=True,
            ended_at__isnull=True,
        )
        .order_by("-started_at")
        .first()
    )

    if not segment:
        return None

    segment.ended_at = now
    segment.is_active = False

    segment.save(
        update_fields=[
            "ended_at",
            "is_active",
            "updated_at",
        ]
    )

    return segment

def _get_session_remaining_seconds(session, now=None):
    """
    Returns remaining ACTIVE riding seconds.

    None -> unlimited
    0    -> target reached
    >0   -> seconds remaining

    PAUSE time is not counted.

    IMPORTANT:
    Reaching 0 does NOT end the session.
    """

    if session.session_limit_seconds is None:
        return None

    now = now or timezone.now()

    elapsed_seconds = _get_session_elapsed_seconds(
        session,
        now=now,
    )

    remaining_seconds = (
        float(session.session_limit_seconds)
        - elapsed_seconds
    )

    return max(
        0,
        round(
            remaining_seconds,
            2,
        ),
    )



def _session_response(
    message,
    action,
    session,
    http_status=status.HTTP_200_OK,
):
    """
    Returns both flat and nested session information.

    session_limit_seconds is only a TARGET.

    Once the target is reached:

        remaining_seconds = 0
        limit_reached = True

    but the session continues riding until the manager presses END.
    """

    now = timezone.now()

    elapsed_seconds = (
        _get_session_elapsed_seconds(
            session,
            now=now,
        )
    )

    remaining_seconds = (
        _get_session_remaining_seconds(
            session,
            now=now,
        )
    )

    limit_reached = (
        remaining_seconds is not None
        and remaining_seconds <= 0
    )

    return Response(
        {
            "status": True,
            "message": message,
            "action": action,
            "session_id": str(session.id),

            "session_limit_seconds": (
                session.session_limit_seconds
            ),

            "elapsed_seconds": (
                elapsed_seconds
            ),

            "remaining_seconds": (
                remaining_seconds
            ),

            "limit_reached": (
                limit_reached
            ),

            "data": {
                "id": str(session.id),

                "participant_id": (
                    session.participant_id
                ),

                "participant_name": (
                    session.participant.name
                ),

                "action": action,

                "session_limit_seconds": (
                    session.session_limit_seconds
                ),

                "elapsed_seconds": (
                    elapsed_seconds
                ),

                "remaining_seconds": (
                    remaining_seconds
                ),

                "limit_reached": (
                    limit_reached
                ),

                "started_at": session.started_at,
                "ended_at": session.ended_at,

                "is_active": session.is_active,
                "is_paused": session.is_paused,
                "is_ended": session.is_ended,
            },
        },
        status=http_status,
    )


def _error(
    message,
    http_status=status.HTTP_400_BAD_REQUEST,
    **extra,
):
    body = {
        "status": False,
        "message": message,
    }

    body.update(extra)

    return Response(
        body,
        status=http_status,
    )


# ================================================================
# AUTH
# ================================================================

class LoginAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):

        serializer = LoginSerializer(
            data=request.data
        )

        if serializer.is_valid():

            user = serializer.validated_data["user"]

            refresh = RefreshToken.for_user(user)

            return Response(
                {
                    "status": True,
                    "message": "Login successful.",

                    "data": {
                        "user_id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "access": str(
                            refresh.access_token
                        ),
                        "refresh": str(refresh),
                    },
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "status": False,
                "message": "Invalid username or password.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


class LogoutAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):

        try:

            refresh_token = request.data["refresh"]

            token = RefreshToken(
                refresh_token
            )

            token.blacklist()

            return Response(
                {
                    "status": True,
                    "message": "Logout successful.",
                }
            )

        except Exception:

            return Response(
                {
                    "status": False,
                    "message": "Invalid refresh token.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


# ================================================================
# CYCLE
# ================================================================

class CycleAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk=None):

        if pk:

            try:
                cycle = Cycle.objects.get(
                    pk=pk
                )

            except Cycle.DoesNotExist:

                return Response(
                    {
                        "status": False,
                        "message": "Cycle not found.",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "status": True,
                    "message": "Cycle fetched successfully.",
                    "data": CycleSerializer(
                        cycle
                    ).data,
                },
                status=status.HTTP_200_OK,
            )

        cycles = (
            Cycle.objects
            .all()
            .order_by("id")
        )

        return Response(
            {
                "status": True,
                "message": "Cycles fetched successfully.",
                "data": CycleSerializer(
                    cycles,
                    many=True,
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):

        serializer = CycleSerializer(
            data=request.data
        )

        if serializer.is_valid():

            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Cycle created successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {
                "status": False,
                "message": (
                    f"Cycle "
                    f"{request.data.get('cycle_no')} "
                    f"already exists."
                ),
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def put(self, request, pk):

        try:
            cycle = Cycle.objects.get(
                pk=pk
            )

        except Cycle.DoesNotExist:

            return Response(
                {
                    "status": False,
                    "message": "Cycle not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CycleSerializer(
            cycle,
            data=request.data,
            partial=True,
        )

        if serializer.is_valid():

            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Cycle updated successfully.",
                    "data": serializer.data,
                }
            )

        return Response(
            {
                "status": False,
                "message": "Unable to update cycle.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def delete(self, request, pk):

        try:
            cycle = Cycle.objects.get(
                pk=pk
            )

        except Cycle.DoesNotExist:

            return Response(
                {
                    "status": False,
                    "message": "Cycle not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        cycle.delete()

        return Response(
            {
                "status": True,
                "message": "Cycle deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )


# ================================================================
# PARTICIPANT
# ================================================================

class ParticipentAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk=None):

        if pk:

            try:
                participent = Participent.objects.get(
                    pk=pk
                )

            except Participent.DoesNotExist:

                return Response(
                    {
                        "status": False,
                        "message": "Participant not found.",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "status": True,
                    "message": "Participant fetched successfully.",
                    "data": ParticipentSerializer(
                        participent
                    ).data,
                },
                status=status.HTTP_200_OK,
            )

        participents = (
            Participent.objects
            .all()
            .order_by("id")
        )

        return Response(
            {
                "status": True,
                "message": "Participants fetched successfully.",
                "data": ParticipentSerializer(
                    participents,
                    many=True,
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):

        serializer = ParticipentSerializer(
            data=request.data
        )

        if serializer.is_valid():

            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Participant created successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {
                "status": False,
                "message": "Unable to create participant.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def put(self, request, pk):

        try:
            participent = Participent.objects.get(
                pk=pk
            )

        except Participent.DoesNotExist:

            return Response(
                {
                    "status": False,
                    "message": "Participant not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ParticipentSerializer(
            participent,
            data=request.data,
            partial=True,
        )

        if serializer.is_valid():

            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Participant updated successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "status": False,
                "message": "Unable to update participant.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def delete(self, request, pk):

        try:
            participent = Participent.objects.get(
                pk=pk
            )

        except Participent.DoesNotExist:

            return Response(
                {
                    "status": False,
                    "message": "Participant not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        participent.delete()

        return Response(
            {
                "status": True,
                "message": "Participant deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )



# ================================================================
# CREATE PARTICIPANT + ALLOCATE TO CYCLE
# ================================================================

class CreateAndAllocateParticipantAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    @transaction.atomic
    def post(self, request):

        cycle_id = request.data.get("cycle")

        if cycle_id in (None, ""):
            return _error(
                "Cycle is required."
            )

        # --------------------------------------------------------
        # Validate cycle
        # --------------------------------------------------------

        try:
            cycle = Cycle.objects.get(
                pk=cycle_id
            )

        except Cycle.DoesNotExist:
            return _error(
                "Selected cycle does not exist.",
                status.HTTP_404_NOT_FOUND,
            )

        # --------------------------------------------------------
        # Create participant
        # --------------------------------------------------------

        participant_data = request.data.copy()

        # Do not send cycle to participant serializer.
        participant_data.pop(
            "cycle",
            None
        )

        participant_serializer = ParticipentSerializer(
            data=participant_data
        )

        if not participant_serializer.is_valid():

            return _error(
                "Unable to create participant.",
                errors=participant_serializer.errors,
            )

        participant = participant_serializer.save()

        # --------------------------------------------------------
        # Check whether cycle already has an allocation.
        #
        # If it does, DON'T create another ParticipentCycle.
        # Instead add the newly created participant to the
        # existing cycle's roster.
        # --------------------------------------------------------

        allocation = (
            ParticipentCycle.objects
            .filter(
                cycle=cycle
            )
            .prefetch_related(
                "other_participant"
            )
            .first()
        )

        if allocation:

            # ----------------------------------------------------
            # Add new participant to existing roster.
            # ----------------------------------------------------

            allocation.other_participant.add(
                participant
            )

            return Response(
                {
                    "status": True,
                    "message": (
                        "Participant created and "
                        "added to the existing cycle successfully."
                    ),
                    "data": {
                        "participant": (
                            ParticipentSerializer(
                                participant
                            ).data
                        ),

                        "allocation": (
                            ParticipentCycleSerializer(
                                allocation,
                                context={
                                    "request": request
                                },
                            ).data
                        ),
                    },
                },
                status=status.HTTP_201_CREATED,
            )

        # --------------------------------------------------------
        # No allocation exists yet.
        #
        # Create the normal active allocation.
        # --------------------------------------------------------

        allocation_data = {
            "cycle": cycle.id,
            "participent": participant.id,
        }

        allocation_serializer = ParticipentCycleSerializer(
            data=allocation_data,
            context={
                "request": request
            },
        )

        if not allocation_serializer.is_valid():

            return _error(
                "Participant was created, but cycle allocation failed.",
                errors=allocation_serializer.errors,
            )

        allocation = allocation_serializer.save()

        # --------------------------------------------------------
        # Add participant to roster as well.
        # --------------------------------------------------------

        allocation.other_participant.add(
            participant
        )

        # --------------------------------------------------------
        # Return both
        # --------------------------------------------------------

        return Response(
            {
                "status": True,
                "message": (
                    "Participant created and "
                    "allocated successfully."
                ),
                "data": {
                    "participant": (
                        ParticipentSerializer(
                            participant
                        ).data
                    ),

                    "allocation": (
                        ParticipentCycleSerializer(
                            allocation,
                            context={
                                "request": request
                            },
                        ).data
                    ),
                },
            },
            status=status.HTTP_201_CREATED,
        )
# ================================================================
# PARTICIPANT <-> CYCLE ALLOCATION
# ================================================================

class ParticipentCycleAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    # ------------------------------------------------------------
    # GET
    # ------------------------------------------------------------

    def get(self, request, pk=None):

        if pk:

            try:

                allocation = (
                    ParticipentCycle.objects
                    .select_related(
                        "participent",
                        "cycle",
                    )
                    .prefetch_related(
                        "other_participant"
                    )
                    .get(pk=pk)
                )

            except ParticipentCycle.DoesNotExist:

                return Response(
                    {
                        "status": False,
                        "message": "Allocation not found.",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = ParticipentCycleSerializer(
                allocation,
                context={
                    "request": request
                },
            )

            return Response(
                {
                    "status": True,
                    "message": "Allocation fetched successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        allocations = (
            ParticipentCycle.objects
            .select_related(
                "participent",
                "cycle",
            )
            .prefetch_related(
                "other_participant"
            )
            .all()
            .order_by("id")
        )

        serializer = ParticipentCycleSerializer(
            allocations,
            many=True,
            context={
                "request": request
            },
        )

        return Response(
            {
                "status": True,
                "message": "Allocations fetched successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------
    # POST
    # ------------------------------------------------------------

    def post(self, request):

        cycle_id = request.data.get("cycle")
        participent_id = request.data.get(
            "participent"
        )

        roster_ids = (
            request.data.get("roster", [])
            or []
        )

        if ParticipentCycle.objects.filter(
            cycle_id=cycle_id
        ).exists():

            return Response(
                {
                    "status": False,
                    "message": "Cycle is already allocated.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ParticipentCycleSerializer(
            data=request.data,
            context={
                "request": request
            },
        )

        if not serializer.is_valid():

            return Response(
                {
                    "status": False,
                    "message": "Unable to allocate cycle.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():

            allocation = serializer.save()

            roster = set()

            if isinstance(
                roster_ids,
                list,
            ):

                for pid in roster_ids:

                    try:
                        roster.add(
                            int(pid)
                        )

                    except (
                        TypeError,
                        ValueError,
                    ):
                        continue

            if participent_id not in (
                None,
                "",
            ):

                try:
                    roster.add(
                        int(participent_id)
                    )

                except (
                    TypeError,
                    ValueError,
                ):
                    pass

            allocation.other_participant.set(
                roster
            )

        return Response(
            {
                "status": True,
                "message": "Cycle allocated successfully.",
                "data": ParticipentCycleSerializer(
                    allocation,
                    context={
                        "request": request
                    },
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )

    # ------------------------------------------------------------
    # PUT
    # ------------------------------------------------------------

    def put(self, request, pk):

        cycle_id = request.data.get(
            "cycle"
        )

        new_participent_id = request.data.get(
            "participent"
        )

        roster_ids = request.data.get(
            "roster"
        )

        update_power = request.data.get(
            "update_power",
            False,
        )

        # --------------------------------------------------------
        # Validate meter values.
        # --------------------------------------------------------

        try:

            power = float(
                request.data.get(
                    "power",
                    0,
                )
                or 0
            )

            voltage = float(
                request.data.get(
                    "voltage",
                    0,
                )
                or 0
            )

            amperage = float(
                request.data.get(
                    "amperage",
                    0,
                )
                or 0
            )

        except (
            TypeError,
            ValueError,
        ):

            return _error(
                "power/voltage/amperage must be numbers."
            )

        # --------------------------------------------------------
        # Validate participant.
        # --------------------------------------------------------

        new_participant_id = None

        if new_participent_id not in (
            None,
            "",
        ):

            try:
                new_participant_id = int(
                    new_participent_id
                )

            except (
                TypeError,
                ValueError,
            ):

                return _error(
                    "Invalid participant ID."
                )

        # --------------------------------------------------------
        # Validate cycle.
        # --------------------------------------------------------

        new_cycle_id = None

        if cycle_id not in (
            None,
            "",
        ):

            try:
                new_cycle_id = int(
                    cycle_id
                )

            except (
                TypeError,
                ValueError,
            ):

                return _error(
                    "Invalid cycle ID."
                )

        # --------------------------------------------------------
        # Validate roster.
        # --------------------------------------------------------

        roster = None

        if roster_ids is not None:

            if not isinstance(
                roster_ids,
                list,
            ):

                return _error(
                    "roster must be a list."
                )

            roster = set()

            for pid in roster_ids:

                try:
                    roster.add(
                        int(pid)
                    )

                except (
                    TypeError,
                    ValueError,
                ):
                    continue

        with transaction.atomic():

            allocation = get_object_or_404(
                ParticipentCycle.objects.select_for_update(),
                pk=pk,
            )

            old_participant_id = (
                allocation.participent_id
            )

            old_cycle_id = (
                allocation.cycle_id
            )

            old_cycle = allocation.cycle

            participant_changed = (
                new_participant_id is not None
                and new_participant_id
                != old_participant_id
            )

            cycle_changed = (
                new_cycle_id is not None
                and new_cycle_id
                != old_cycle_id
            )

            new_participant = None

            if participant_changed:

                new_participant = get_object_or_404(
                    Participent,
                    pk=new_participant_id,
                )

            # ----------------------------------------------------
            # One allocation per cycle.
            # ----------------------------------------------------

            if cycle_changed:

                duplicate = (
                    ParticipentCycle.objects
                    .filter(
                        cycle_id=new_cycle_id
                    )
                    .exclude(pk=pk)
                    .exists()
                )

                if duplicate:

                    return _error(
                        "Cycle is already allocated."
                    )

            # ----------------------------------------------------
            # Validate before changing anything.
            # ----------------------------------------------------

            serializer = ParticipentCycleSerializer(
                allocation,
                data=request.data,
                partial=True,
                context={
                    "request": request
                },
            )

            if not serializer.is_valid():

                return _error(
                    "Unable to update allocation.",
                    errors=serializer.errors,
                )

            now = timezone.now()

            # ----------------------------------------------------
            # Close Cycle History session if rider/cycle changes.
            # Meter collection continues.
            # ----------------------------------------------------

            if (
                participant_changed
                or cycle_changed
            ):

                close_open_cycle_ride_session(
                    old_cycle,
                    now=now,
                )

            # ----------------------------------------------------
            # Legacy ParticipantCyclingDuration.
            # ----------------------------------------------------

            if participant_changed:

                old_duration = (
                    ParticipantCyclingDuration.objects
                    .filter(
                        participant_id=old_participant_id,
                        is_ended=False,
                    )
                    .order_by("-start_at")
                    .first()
                )

                if old_duration:

                    old_duration.end_at = now
                    old_duration.is_ended = True

                    old_duration.save(
                        update_fields=[
                            "end_at",
                            "is_ended",
                        ]
                    )

                ParticipantCyclingDuration.objects.create(
                    participant=new_participant,
                    start_at=now,
                    is_ended=False,
                )

            allocation = serializer.save()

            # ----------------------------------------------------
            # Roster.
            # ----------------------------------------------------

            if roster is not None:

                roster.add(
                    allocation.participent_id
                )

                allocation.other_participant.set(
                    roster
                )

            else:

                allocation.other_participant.add(
                    allocation.participent_id
                )

            # ----------------------------------------------------
            # Current meter values + totals.
            # ----------------------------------------------------

            ParticipentCycle.objects.filter(
                pk=pk
            ).update(
                power=power,
                voltage=voltage,
                amperage=amperage,
                total_power=(
                    F("total_power")
                    + power
                ),
                total_voltage=(
                    F("total_voltage")
                    + voltage
                ),
                total_amperage=(
                    F("total_amperage")
                    + amperage
                ),
            )

            allocation.refresh_from_db()

            # ----------------------------------------------------
            # PowerMonitor.
            # ----------------------------------------------------

            if update_power:

                open_session = (
                    CycleRideSession.objects
                    .filter(
                        cycle=allocation.cycle,
                        is_active=True,
                        is_ended=False,
                    )
                    .select_related(
                        "participant"
                    )
                    .order_by(
                        "-created_at"
                    )
                    .first()
                )

                # --------------------------------------------------------
                # IMPORTANT:
                #
                # Only save historical PowerMonitor data while the
                # participant is actively RIDING.
                #
                # START  -> SAVE
                # PAUSE  -> DON'T SAVE
                # RESUME -> SAVE
                # END    -> DON'T SAVE
                # No session -> DON'T SAVE
                # --------------------------------------------------------

                if open_session:

                    PowerMonitor.objects.create(
                        participent=allocation,
                        participant_data=open_session.participant,
                        current_power=power,
                        current_voltage=voltage,
                        current_amperage=amperage,
                        total_power=allocation.total_power,
                        total_voltage=allocation.total_voltage,
                        total_amperage=allocation.total_amperage,
                    )

        return Response(
            {
                "status": True,
                "message": "Allocation updated successfully.",
                "data": ParticipentCycleSerializer(
                    allocation,
                    context={
                        "request": request
                    },
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------

    def delete(self, request, pk):

        with transaction.atomic():

            try:

                allocation = (
                    ParticipentCycle.objects
                    .select_for_update()
                    .get(pk=pk)
                )

            except ParticipentCycle.DoesNotExist:

                return Response(
                    {
                        "status": False,
                        "message": "Allocation not found.",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            close_open_cycle_ride_session(
                allocation.cycle,
                timezone.now(),
            )

            allocation.delete()

        return Response(
            {
                "status": True,
                "message": "Allocation deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )


class ParticipentCycleDurationAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk=None):

        if pk:

            try:

                allocation = (
                    ParticipentCycle.objects.get(
                        pk=pk
                    )
                )

            except ParticipentCycle.DoesNotExist:

                return Response(
                    {
                        "status": False,
                        "message": "Allocation not found.",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = ParticipentCycleDurationSerializer(
                allocation,
                context={
                    "request": request
                },
            )

            return Response(
                {
                    "status": True,
                    "message": "Allocation fetched successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        allocations = (
            ParticipentCycle.objects
            .select_related(
                "participent",
                "cycle",
            )
            .prefetch_related(
                "other_participant"
            )
            .all()
            .order_by("id")
        )

        serializer = ParticipentCycleDurationSerializer(
            allocations,
            many=True,
            context={
                "request": request
            },
        )

        return Response(
            {
                "status": True,
                "message": "Allocations fetched successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


# ================================================================
# SCREEN
# ================================================================

class ScreenAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk=None):

        if pk:

            try:
                screen = Screen.objects.get(
                    pk=pk
                )

            except Screen.DoesNotExist:

                return Response(
                    {
                        "status": False,
                        "message": "Screen not found.",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "status": True,
                    "message": "Screen fetched successfully.",
                    "data": ScreenSerializer(
                        screen
                    ).data,
                },
                status=status.HTTP_200_OK,
            )

        screens = (
            Screen.objects
            .all()
            .order_by("id")
        )

        return Response(
            {
                "status": True,
                "message": "Screens fetched successfully.",
                "data": ScreenSerializer(
                    screens,
                    many=True,
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):

        serializer = ScreenSerializer(
            data=request.data
        )

        if serializer.is_valid():

            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Screen created successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {
                "status": False,
                "message": "Unable to create screen.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def put(self, request, pk):

        try:
            screen = Screen.objects.get(
                pk=pk
            )

        except Screen.DoesNotExist:

            return Response(
                {
                    "status": False,
                    "message": "Screen not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ScreenSerializer(
            screen,
            data=request.data,
            partial=True,
        )

        if serializer.is_valid():

            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Screen updated successfully.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "status": False,
                "message": "Unable to update screen.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def delete(self, request, pk):

        try:
            screen = Screen.objects.get(
                pk=pk
            )

        except Screen.DoesNotExist:

            return Response(
                {
                    "status": False,
                    "message": "Screen not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        screen.delete()

        return Response(
            {
                "status": True,
                "message": "Screen deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )


# ================================================================
# AVAILABLE CYCLES / PARTICIPANTS
# ================================================================

class Available_Cycle(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):

        try:

            allocated_cycles = (
                ParticipentCycle.objects
                .values_list(
                    "cycle_id",
                    flat=True,
                )
            )

            available_cycles = (
                Cycle.objects
                .exclude(
                    id__in=allocated_cycles
                )
            )

            return Response(
                {
                    "status": True,
                    "message": "Available cycles fetched successfully.",
                    "data": CycleSerializer(
                        available_cycles,
                        many=True,
                    ).data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": "Error fetching available cycles.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AvailableParticipant(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):

        try:

            active_ids = (
                ParticipentCycle.objects
                .values_list(
                    "participent_id",
                    flat=True,
                )
            )

            roster_ids = (
                ParticipentCycle.objects
                .values_list(
                    "other_participant__id",
                    flat=True,
                )
            )

            allocated_ids = (
                set(active_ids)
                | set(roster_ids)
            )

            allocated_ids.discard(None)

            available_data = (
                Participent.objects
                .exclude(
                    id__in=allocated_ids
                )
            )

            return Response(
                {
                    "status": True,
                    "message": (
                        "Available participants "
                        "fetched successfully."
                    ),
                    "data": ParticipentSerializer(
                        available_data,
                        many=True,
                    ).data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Error fetching "
                        "available participants"
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ================================================================
# FREE TEXT
# ================================================================

def _free_text_payload(
    request,
    item,
    date_field,
):

    return {
        "id": item.id,
        "text": item.text,
        "style": item.style,

        "bg_image_url": (
            request.build_absolute_uri(
                item.bg_image.url
            )
            if item.bg_image
            else None
        ),

        date_field: getattr(
            item,
            date_field,
        ),
    }


class LastFreeTextApiView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):

        try:

            last_free_text = (
                FreeText.objects.last()
            )

            if last_free_text:

                return Response(
                    {
                        "status": True,
                        "message": (
                            "Last free text "
                            "fetched successfully."
                        ),
                        "data": {
                            "text": last_free_text.text,
                            "created_at": (
                                last_free_text.created_at
                            ),
                            "style": last_free_text.style,
                            "bg_image_url": (
                                request.build_absolute_uri(
                                    last_free_text
                                    .bg_image.url
                                )
                                if last_free_text.bg_image
                                else None
                            ),
                        },
                    },
                    status=status.HTTP_200_OK,
                )

            return Response(
                {
                    "status": False,
                    "message": "No free text found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Error fetching "
                        "last free text."
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FreeTextDraftAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):

        try:

            draft = (
                FreeTextDraft.objects.first()
            )

            if not draft:

                return Response(
                    {
                        "status": True,
                        "message": (
                            "No free text "
                            "draft found."
                        ),
                        "data": None,
                    },
                    status=status.HTTP_200_OK,
                )

            return Response(
                {
                    "status": True,
                    "message": (
                        "Free text draft "
                        "fetched successfully."
                    ),
                    "data": _free_text_payload(
                        request,
                        draft,
                        "updated_at",
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Error fetching "
                        "free text draft."
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def put(self, request):

        try:

            draft = (
                FreeTextDraft.objects.first()
            )

            if draft:

                draft.text = request.data.get(
                    "text",
                    "",
                )

                draft.style = request.data.get(
                    "style",
                    {},
                )

            else:

                draft = FreeTextDraft(
                    text=request.data.get(
                        "text",
                        "",
                    ),
                    style=request.data.get(
                        "style",
                        {},
                    ),
                )

            bg_image = request.FILES.get(
                "bgImage"
            )

            remove_bg_image = (
                str(
                    request.data.get(
                        "removeBgImage",
                        "",
                    )
                ).lower()
                == "true"
            )

            if remove_bg_image:

                if draft.bg_image:
                    draft.bg_image.delete(
                        save=False
                    )

                draft.bg_image = None

            elif bg_image:

                if draft.bg_image:
                    draft.bg_image.delete(
                        save=False
                    )

                draft.bg_image = bg_image

            draft.save()

            return Response(
                {
                    "status": True,
                    "message": (
                        "Free text draft "
                        "saved successfully."
                    ),
                    "data": _free_text_payload(
                        request,
                        draft,
                        "updated_at",
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Error saving "
                        "free text draft."
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FreeTextHistoryAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):

        try:

            history = (
                FreeText.objects
                .all()
                .order_by("-created_at")
            )

            data = [
                _free_text_payload(
                    request,
                    item,
                    "created_at",
                )
                for item in history
            ]

            return Response(
                {
                    "status": True,
                    "message": (
                        "Free text history "
                        "fetched successfully."
                    ),
                    "data": data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Error fetching "
                        "free text history."
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FreeTextHistoryDetailAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk):

        try:

            free_text = (
                FreeText.objects.get(
                    pk=pk
                )
            )

            return Response(
                {
                    "status": True,
                    "message": (
                        "Free text history "
                        "item fetched successfully."
                    ),
                    "data": _free_text_payload(
                        request,
                        free_text,
                        "created_at",
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except FreeText.DoesNotExist:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Free text history "
                        "item not found."
                    ),
                },
                status=status.HTTP_404_NOT_FOUND,
            )


# ================================================================
# APP THEME
# ================================================================

class AppThemeAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):

        name = request.query_params.get(
            "name"
        )

        try:

            if name:

                app_theme = (
                    AppTheme.objects
                    .filter(name=name)
                    .first()
                )

            else:

                app_theme = (
                    AppTheme.objects
                    .filter(is_active=True)
                    .first()
                    or AppTheme.objects.first()
                )

            if not app_theme:

                return Response(
                    {
                        "status": False,
                        "message": "No app theme found.",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "status": True,
                    "message": (
                        "App theme "
                        "fetched successfully."
                    ),
                    "data": AppThemeSerializer(
                        app_theme,
                        many=False,
                    ).data,
                }
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Error fetching "
                        "app theme."
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):

        try:

            data = request.data.copy()

            name = data.get(
                "name"
            )

            data.setdefault(
                "is_active",
                True,
            )

            instance = (
                AppTheme.objects
                .filter(name=name)
                .first()
                if name
                else None
            )

            serializer = AppThemeSerializer(
                instance,
                data=data,
                partial=False,
            )

            if not serializer.is_valid():

                return Response(
                    {
                        "status": False,
                        "message": (
                            "Invalid app theme data."
                        ),
                        "errors": serializer.errors,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            saved = serializer.save()

            try:

                saved.full_clean(
                    exclude=[
                        "created_at",
                        "updated_at",
                    ]
                )

            except DjangoValidationError as e:

                if instance is None:
                    saved.delete()

                return Response(
                    {
                        "status": False,
                        "message": (
                            "Invalid color/theme value."
                        ),
                        "errors": e.message_dict,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status": True,
                    "message": (
                        "App theme "
                        "saved successfully."
                    ),
                    "data": AppThemeSerializer(
                        saved
                    ).data,
                },
                status=(
                    status.HTTP_201_CREATED
                    if instance is None
                    else status.HTTP_200_OK
                ),
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Error saving "
                        "app theme."
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AppThemeListAPIViews(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):

        try:

            app_themes = (
                AppTheme.objects.all()
            )

            serializer = AppThemeListSerializer(
                app_themes,
                many=True,
            )

            return Response(
                {
                    "status": True,
                    "message": (
                        "App themes "
                        "fetched successfully."
                    ),
                    "data": serializer.data,
                }
            )

        except Exception as e:

            return Response(
                {
                    "status": False,
                    "message": (
                        "Error fetching "
                        "app themes."
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ================================================================
# CYCLE HISTORY
#
# GET
# /api/admin/cycle-history/
#
# Returns all cycles with:
# - cycle id
# - cycle number
# - controller number
# - participants
#
#
# GET
# /api/admin/cycle-history/<cycle_id>/
#
# Returns:
# - sessions
# - segments
# - duration
# - power statistics
# - voltage statistics
# - session limit
# - remaining active riding time
#
#
# POST
# /api/admin/cycle-history/<cycle_id>/
#
# START:
# {
#     "action": "start",
#     "participant_id": 1,
#     "duration_seconds": 600
# }
#
# duration_seconds:
#     omitted / "" -> unlimited
#     600           -> 10 minutes active riding
#
# PAUSE:
# {
#     "action": "pause"
# }
#
# RESUME:
# {
#     "action": "resume"
# }
#
# END:
# {
#     "action": "end"
# }
#
# ================================================================

class CycleHistoryAPIView(APIView):

    permission_classes = [AllowAny]
    authentication_classes = []

    # ------------------------------------------------------------
    # GET
    # ------------------------------------------------------------

    def get(self, request, cycle_id=None):

        # ========================================================
        # GET ALL CYCLES
        # ========================================================

        if cycle_id is None:

            cycles = (
                Cycle.objects
                .all()
                .order_by("id")
            )

            allocations = {
                allocation.cycle_id: allocation
                for allocation in (
                    ParticipentCycle.objects
                    .select_related("participent")
                    .prefetch_related(
                        "other_participant"
                    )
                )
            }

            data = []

            for cycle in cycles:

                allocation = allocations.get(
                    cycle.id
                )

                participants = []

                if allocation:

                    seen = set()

                    # ------------------------------------------------
                    # Active participant first.
                    # ------------------------------------------------

                    if allocation.participent:

                        participants.append(
                            {
                                "id": (
                                    allocation
                                    .participent.id
                                ),
                                "name": (
                                    allocation
                                    .participent.name
                                ),
                                "is_active": (
                                    allocation.active_participant_id
                                    == allocation.participent.id
                                ),
                            }
                        )

                        seen.add(
                            allocation
                            .participent.id
                        )

                    # ------------------------------------------------
                    # Roster participants.
                    # ------------------------------------------------

                    for participant in (
                        allocation
                        .other_participant
                        .all()
                    ):

                        if participant.id in seen:
                            continue

                        seen.add(
                            participant.id
                        )

                        participants.append(
                            {
                                "id": participant.id,
                                "name": participant.name,
                                "is_active": (
                                    allocation.active_participant_id
                                    == participant.id
                                ),
                            }
                        )

                data.append(
                    {
                        "id": cycle.id,
                        "cycle_no": cycle.cycle_no,
                        "controller_no": (
                            cycle.controller_no
                        ),
                        "active_participant_id": (
                            allocation.active_participant_id
                            if allocation
                            else None
                        ),
                        "participants": participants,
                    }
                )

            return Response(
                {
                    "status": True,
                    "data": data,
                },
                status=status.HTTP_200_OK,
            )

        # ========================================================
        # GET ONE CYCLE HISTORY
        # ========================================================

        cycle = get_object_or_404(
            Cycle,
            pk=cycle_id,
        )

        now = timezone.now()

        # --------------------------------------------------------
        # Automatically expire limited active sessions.
        # --------------------------------------------------------

        # sessions_to_check = (
        #     CycleRideSession.objects
        #     .filter(
        #         cycle=cycle,
        #         is_active=True,
        #         is_ended=False,
        #         session_limit_seconds__isnull=False,
        #     )
        #     .prefetch_related("segments")
        # )

        # for session in sessions_to_check:

        #     expire_cycle_ride_session(
        #         session,
        #         now=now,
        #     )

        # --------------------------------------------------------
        # Refetch after possible expiry.
        # --------------------------------------------------------

        sessions = (
            CycleRideSession.objects
            .filter(
                cycle=cycle
            )
            .select_related(
                "participant"
            )
            .prefetch_related(
                "segments"
            )
            .order_by(
                "started_at",
                "created_at",
            )
        )

        history = []

        # ========================================================
        # BUILD HISTORY
        # ========================================================

        for session in sessions:

            segments = sorted(
                session.segments.all(),
                key=lambda segment: (
                    segment.started_at,
                    segment.id,
                ),
            )

            total_duration_seconds = 0.0

            power_values = []
            voltage_values = []
            total_power = 0.0
            total_voltage = 0.0
            peak_power=0.0
            peak_voltage=0.0

            segment_data = []

            # ----------------------------------------------------
            # SEGMENTS
            # ----------------------------------------------------

            for segment in segments:

                # ------------------------------------------------
                # For active segments, use current time.
                #
                # Expired sessions should already have been closed
                # above, so this is mainly for unlimited sessions.
                # ------------------------------------------------

                segment_end = (
                    segment.ended_at
                    or timezone.now()
                )

                duration_seconds = max(
                    0,
                    (
                        segment_end
                        - segment.started_at
                    ).total_seconds(),
                )

                total_duration_seconds += (
                    duration_seconds
                )

                # ------------------------------------------------
                # Meter readings belong to the CYCLE.
                #
                # Do NOT filter PowerMonitor by participant.
                # ------------------------------------------------

                readings = list(
                    PowerMonitor.objects
                    .filter(
                        participent__cycle=cycle,
                        participant_data_id=session.participant_id,
                        updated_at__gte=segment.started_at,
                        updated_at__lte=segment_end,
                    )
                    .order_by("updated_at")
                )

                segment_power_values = [
                    float(reading.current_power or 0)
                    for reading in readings
                ]

                segment_voltage_values = [
                    float(reading.current_voltage or 0)
                    for reading in readings
                ]

                # Keep every reading for session-level average calculation.
                power_values.extend(segment_power_values)
                voltage_values.extend(segment_voltage_values)

                # Sum every meter reading for the session.
                total_power += sum(segment_power_values)
                total_voltage += sum(segment_voltage_values)

                # Track highest reading reached during the session.
                if segment_power_values:
                    peak_power = max(
                        peak_power,
                        max(segment_power_values),
                    )

                if segment_voltage_values:
                    peak_voltage = max(
                        peak_voltage,
                        max(segment_voltage_values),
                    )

                # Metrics for this segment.
                segment_average_power = (
                    sum(segment_power_values) / len(segment_power_values)
                    if segment_power_values
                    else 0
                )

                segment_average_voltage = (
                    sum(segment_voltage_values) / len(segment_voltage_values)
                    if segment_voltage_values
                    else 0
                )

                segment_max_power = (
                    max(segment_power_values)
                    if segment_power_values
                    else 0
                )

                segment_max_voltage = (
                    max(segment_voltage_values)
                    if segment_voltage_values
                    else 0
                )
                

                segment_data.append(
                    {
                        "id": segment.id,

                        "started_at": (
                            segment.started_at
                        ),

                        "ended_at": (
                            segment.ended_at
                        ),

                        "duration_seconds": round(
                            duration_seconds,
                            2,
                        ),

                        "average_power": round(segment_average_power, 2),

                        "average_voltage": round(segment_average_voltage, 2),

                        "max_power": round(segment_max_power, 2),

                        "max_voltage": round(segment_max_voltage, 2),

                        "is_active": (
                            segment.is_active
                        ),
                    }
                )

            # ----------------------------------------------------
            # SESSION AVERAGES
            # ----------------------------------------------------

            average_power = (
                sum(power_values)
                / len(power_values)
                if power_values
                else 0
            )

            average_voltage = (
                sum(voltage_values)
                / len(voltage_values)
                if voltage_values
                else 0
            )

            # ----------------------------------------------------
            # Remaining active riding time.
            # ----------------------------------------------------

            remaining_seconds = (
                _get_session_remaining_seconds(
                    session,
                    now=now,
                )
            )

            limit_reached = (
                remaining_seconds is not None
                and remaining_seconds <= 0
            )

            # ----------------------------------------------------
            # HISTORY ITEM
            # ----------------------------------------------------

            history.append(
                {
                    "id": str(
                        session.id
                    ),

                    "cycle_id": cycle.id,

                    "cycle_no": (
                        cycle.cycle_no
                    ),

                    "participant_id": (
                        session
                        .participant
                        .id
                    ),

                    "participant_name": (
                        session
                        .participant
                        .name
                    ),
                    "participant_email": session.participant.email or "",
                    "participant_phone": session.participant.phone or "",

                    "started_at": (
                        session.started_at
                    ),

                    "ended_at": (
                        session.ended_at
                    ),

                    "is_active": (
                        session.is_active
                    ),

                    "is_paused": (
                        session.is_paused
                    ),

                    "is_ended": (
                        session.is_ended
                    ),

                    "duration_seconds": round(
                        total_duration_seconds,
                        2,
                    ),
                    "elapsed_seconds": round(
                        total_duration_seconds,
                        2,
                    ),

                    "session_limit_seconds": (
                        session
                        .session_limit_seconds
                    ),

                    "remaining_seconds": (
                        remaining_seconds
                    ),
                    "limit_reached": (
                        limit_reached
                    ),

                    "average_power": round(
                        average_power,
                        2,
                    ),

                    "average_voltage": round(
                        average_voltage,
                        2,
                    ),
                    "total_power": round(total_power, 2),

                    "total_voltage": round(total_voltage, 2),
                    "peak_power": round(peak_power,2,),

                    "peak_voltage": round(peak_voltage,2,),

                    "segments": segment_data,



                }
            )

        # ========================================================
        # RESPONSE
        # ========================================================

        return Response(
            {
                "status": True,

                "cycle": {
                    "id": cycle.id,
                    "cycle_no": cycle.cycle_no,
                    "controller_no": (
                        cycle.controller_no
                    ),
                },

                # Both keys are returned for frontend compatibility.
                "history": history,
                "data": history,
            },
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------
    # POST
    # ------------------------------------------------------------

    @transaction.atomic
    def post(self, request, cycle_id=None):

        if not cycle_id:

            return _error(
                "cycle_id is required."
            )

        action = str(
            request.data.get(
                "action",
                "",
            )
        ).strip().lower()

        # Existing frontend compatibility.
        if action == "end_save":
            action = "end"

        if action not in {
            "start",
            "pause",
            "resume",
            "end",
        }:

            return _error(
                "Invalid action. "
                "Use start, pause, resume or end."
            )

        # --------------------------------------------------------
        # Lock cycle while modifying its ride session.
        # --------------------------------------------------------

        cycle = get_object_or_404(
            Cycle.objects.select_for_update(),
            pk=cycle_id,
        )

        now = timezone.now()

        # ========================================================
        # START
        # ========================================================

        if action == "start":

            # ----------------------------------------------------
            # Validate duration BEFORE changing anything.
            # ----------------------------------------------------

            duration_seconds = request.data.get(
                "duration_seconds"
            )

            # Blank / omitted = unlimited.
            if duration_seconds in (
                "",
                None,
            ):

                duration_seconds = None

            else:

                try:

                    duration_seconds = int(
                        duration_seconds
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    return _error(
                        (
                            "Invalid duration_seconds. "
                            "Must be an integer."
                        ),
                        status.HTTP_400_BAD_REQUEST,
                    )

                if duration_seconds <= 0:

                    return _error(
                        (
                            "duration_seconds must "
                            "be greater than 0."
                        ),
                        status.HTTP_400_BAD_REQUEST,
                    )

            # ----------------------------------------------------
            # Get cycle allocation.
            # ----------------------------------------------------

            allocation = (
                ParticipentCycle.objects
                .filter(
                    cycle=cycle
                )
                .prefetch_related(
                    "other_participant"
                )
                .first()
            )

            if not allocation:

                return _error(
                    "No participant is allocated to this cycle."
                )

            # ----------------------------------------------------
            # Selected participant.
            # ----------------------------------------------------

            raw_id = request.data.get(
                "participant_id"
            )

            if raw_id in (
                None,
                "",
            ):

                selected_id = (
                    allocation
                    .participent_id
                )

            else:

                try:

                    selected_id = int(
                        raw_id
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    return _error(
                        "Invalid participant_id."
                    )

            # ----------------------------------------------------
            # Participant must belong to cycle.
            # ----------------------------------------------------

            allowed_ids = {
                allocation.participent_id
            }

            allowed_ids.update(
                allocation
                .other_participant
                .values_list(
                    "id",
                    flat=True,
                )
            )

            if selected_id not in allowed_ids:

                return _error(
                    (
                        "Selected participant is "
                        "not allocated to this cycle."
                    )
                )

            participant = get_object_or_404(
                Participent,
                pk=selected_id,
            )

            # ----------------------------------------------------
            # Find current open session.
            # ----------------------------------------------------

            open_session = (
                CycleRideSession.objects
                .select_for_update()
                .select_related(
                    "participant"
                )
                .filter(
                    cycle=cycle,
                    is_ended=False,
                )
                .order_by(
                    "-created_at"
                )
                .first()
            )
                       # ------------------------------------------------
                # Existing session still open.
                # ------------------------------------------------

            if open_session:

                if open_session.participant_id == participant.id:

                    # Same participant, already riding.
                    if open_session.is_active:
                        return _error("This participant is already riding.")

                    # Same participant, paused -> START acts as RESUME.
                    if open_session.is_paused:
                        CycleRideSegment.objects.create(
                            session=open_session,
                            started_at=now,
                            ended_at=None,
                            is_active=True,)
                        open_session.is_active = True
                        open_session.is_paused = False
                        open_session.save(
                            update_fields=[
                                "is_active",
                                "is_paused",
                                "updated_at",])

                            # Keep Cycle Allocations in sync.
                        allocation.active_participant = participant

                        allocation.save(
                            update_fields=[
                                "active_participant",
                                "updated_at",
                            ]
                        )
                        return _session_response(
                            "Ride resumed successfully.",
                            "resume",
                            open_session,
                        )

                    # Different participant (or inconsistent state):
                    # end the previous session before starting a new one.
                close_open_cycle_ride_session(
                    cycle,
                    now=now,
                )

            # ----------------------------------------------------
            # If the selected participant differs from the current
            # primary on the allocation, update it so Cycle
            # Allocations page stays in sync.
            # ----------------------------------------------------

            if allocation.participent_id != participant.id:
                allocation.participent = participant
                allocation.save(update_fields=["participent"])
                allocation.other_participant.add(participant)

            # ----------------------------------------------------
            # Create new session.
            # ----------------------------------------------------

            session = CycleRideSession.objects.create(
                cycle=cycle,
                participant=participant,

                started_at=now,
                ended_at=None,

                is_active=True,
                is_paused=False,
                is_ended=False,

                session_limit_seconds=(
                    duration_seconds
                ),
            )

            # ----------------------------------------------------
            # First active riding segment.
            # ----------------------------------------------------

            CycleRideSegment.objects.create(
                session=session,
                started_at=now,
                ended_at=None,
                is_active=True,
            )
            # ----------------------------------------------------
            # IMPORTANT:
            # Keep allocation.participent unchanged.
            # Only change who is currently active.
            # ----------------------------------------------------

            allocation.active_participant = participant

            allocation.save(
                update_fields=[
                    "active_participant",
                    "updated_at",
                ]
            )


            return _session_response(
                "Ride started successfully.",
                "start",
                session,
                status.HTTP_201_CREATED,
            )

        # ========================================================
        # PAUSE / RESUME / END
        # ========================================================

        session = (
            CycleRideSession.objects
            .select_for_update()
            .select_related(
                "participant"
            )
            .filter(
                cycle=cycle,
                is_ended=False,
            )
            .order_by(
                "-created_at"
            )
            .first()
        )

        if not session:

            return _error(
                "No active ride session."
            )

        # --------------------------------------------------------
        # Check timeout before requested action.
        # --------------------------------------------------------

        # expire_cycle_ride_session(
        #     session,
        #     now=now,
        # )

        # session.refresh_from_db()

        # ========================================================
        # PAUSE
        # ========================================================

        if action == "pause":

            # Session expired while processing request.
            if session.is_ended:

                return _session_response(
                    (
                        "Ride time limit reached. "
                        "Ride ended automatically."
                    ),
                    "end",
                    session,
                )

            if not session.is_active:

                return _error(
                    "Ride is not currently active."
                )

            # Close current active segment.
            _close_active_segment(
                session,
                now,
            )

            session.is_active = False
            session.is_paused = True

            session.save(
                update_fields=[
                    "is_active",
                    "is_paused",
                    "updated_at",
                ]
            )

            return _session_response(
                "Ride paused successfully.",
                "pause",
                session,
            )

        # ========================================================
        # RESUME
        # ========================================================

        if action == "resume":

            if session.is_ended:

                return _error(
                    "Ride session has already ended."
                )

            if not session.is_paused:

                return _error(
                    "Ride is not paused."
                )

            # --------------------------------------------------------
            # IMPORTANT:
            #
            # The configured duration is only a TARGET.
            #
            # Even when:
            #
            #     remaining_seconds == 0
            #
            # the participant is allowed to resume and continue riding.
            # --------------------------------------------------------

            raw_id = request.data.get(
                "participant_id"
            )

            if raw_id not in (
                None,
                "",
            ):

                try:

                    requested_id = int(
                        raw_id
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    return _error(
                        "Invalid participant_id."
                    )

                if (
                    requested_id
                    != session.participant_id
                ):

                    return _error(
                        (
                            "Participant changed. "
                            "Use START to begin a "
                            "new participant session."
                        )
                    )

            # --------------------------------------------------------
            # Create a new active riding segment.
            # --------------------------------------------------------

            CycleRideSegment.objects.create(
                session=session,
                started_at=now,
                ended_at=None,
                is_active=True,
            )

            session.is_active = True
            session.is_paused = False

            session.save(
                update_fields=[
                    "is_active",
                    "is_paused",
                    "updated_at",
                ]
            )

            allocation = (
                ParticipentCycle.objects
                .select_for_update()
                .filter(cycle=cycle)
                .first()
            )

            if allocation:
                allocation.active_participant = session.participant
                allocation.save(
                    update_fields=[
                        "active_participant",
                        "updated_at",
                    ]
                )

            return _session_response(
                "Ride resumed successfully.",
                "resume",
                session,
            )

            # ----------------------------------------------------
            # Optional participant validation.
            # ----------------------------------------------------

            raw_id = request.data.get(
                "participant_id"
            )

            if raw_id not in (
                None,
                "",
            ):

                try:

                    requested_id = int(
                        raw_id
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    return _error(
                        "Invalid participant_id."
                    )

                if (
                    requested_id
                    != session.participant_id
                ):

                    return _error(
                        (
                            "Participant changed. "
                            "Use START to begin a "
                            "new participant session."
                        )
                    )

            # ----------------------------------------------------
            # Create new active segment.
            # ----------------------------------------------------

            CycleRideSegment.objects.create(
                session=session,
                started_at=now,
                ended_at=None,
                is_active=True,
            )

            session.is_active = True
            session.is_paused = False

            session.save(
                update_fields=[
                    "is_active",
                    "is_paused",
                    "updated_at",
                ]
            )

            return _session_response(
                "Ride resumed successfully.",
                "resume",
                session,
            )

        # ========================================================
        # END
        # ========================================================

        if action == "end":

            # ----------------------------------------------------
            # Automatic timeout already ended it.
            # ----------------------------------------------------

            if session.is_ended:

                return _session_response(
                    (
                        "Ride time limit reached. "
                        "Ride ended automatically."
                    ),
                    "end",
                    session,
                )

            # ----------------------------------------------------
            # Close currently active segment.
            #
            # If paused, there is no active segment.
            # ----------------------------------------------------

            _close_active_segment(
                session,
                now,
            )

            session.ended_at = now
            session.is_active = False
            session.is_paused = False
            session.is_ended = True

            session.save(
                update_fields=[
                    "ended_at",
                    "is_active",
                    "is_paused",
                    "is_ended",
                    "updated_at",
                ]
            )

                # --------------------------------------------------------
            # Clear active participant from Cycle Allocation.
            # --------------------------------------------------------

            allocation = (
                ParticipentCycle.objects
                .select_for_update()
                .filter(cycle=cycle)
                .first()
            )

            if allocation:
                allocation.active_participant = None
                allocation.save(
                    update_fields=[
                        "active_participant",
                        "updated_at",
                    ]
                )

            return _session_response(
                "Ride ended and saved successfully.",
                "end",
                session,
            )

        # --------------------------------------------------------
        # Safety fallback.
        # --------------------------------------------------------

        return _error(
            "Unable to process ride action."
        )


# top 10 api

class CycleHistoryTop10APIView(APIView):
    """
    GET
    ---
    /api/admin/cycle-history/<cycle_id>/top-10/

    Returns the top 10 participants for a cycle based on
    total riding duration across all of their sessions.

    Metrics:
        - rank
        - participant_id
        - participant_name
        - total_duration_seconds
        - total_voltage
        - total_power
        - total_amperage
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, cycle_id):

        # --------------------------------------------------------
        # Cycle
        # --------------------------------------------------------

        try:
            cycle = Cycle.objects.get(
                pk=cycle_id
            )
        except Cycle.DoesNotExist:
            return Response(
                {
                    "status": False,
                    "message": "Cycle not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # --------------------------------------------------------
        # Get all sessions for this cycle.
        #
        # We intentionally do NOT filter only ended sessions.
        # This means an active session can also appear in the
        # ranking with its duration calculated up to now.
        # --------------------------------------------------------

        sessions = (
            CycleRideSession.objects
            .filter(
                cycle=cycle,
            )
            .select_related(
                "participant",
            )
            .prefetch_related(
                "segments",
            )
            .order_by(
                "participant_id",
                "started_at",
            )
        )

        # --------------------------------------------------------
        # Group sessions by participant.
        # --------------------------------------------------------

        participant_stats = {}

        for session in sessions:

            participant_id = session.participant_id

            if participant_id not in participant_stats:
                participant_stats[participant_id] = {
                    "participant_id": participant_id,
                    "participant_name": (
                        session.participant.name
                    ),
                    "total_duration_seconds": 0.0,
                    "total_power": 0.0,
                    "total_voltage": 0.0,
                    "total_amperage": 0.0,
                }

            stats = participant_stats[
                participant_id
            ]

            # ----------------------------------------------------
            # Calculate duration from ACTIVE segments.
            #
            # This automatically excludes pause periods.
            # ----------------------------------------------------

            segments = list(
                session.segments.all()
            )

            for segment in segments:

                segment_end = segment.ended_at

                if segment_end is None:
                    segment_end = timezone.now()

                duration_seconds = max(
                    0,
                    (
                        segment_end
                        - segment.started_at
                    ).total_seconds(),
                )

                stats[
                    "total_duration_seconds"
                ] += duration_seconds

                # ------------------------------------------------
                # Meter readings belonging to this exact
                # participant/session segment.
                #
                # PowerMonitor does not have a direct
                # CycleRideSession FK, so we identify readings
                # using:
                #
                #   cycle allocation
                #   participant
                #   segment time range
                # ------------------------------------------------

                readings = (
                    PowerMonitor.objects
                    .filter(
                        participent__cycle=cycle,
                        participant_data_id=participant_id,
                        updated_at__gte=segment.started_at,
                        updated_at__lte=segment_end,
                    )
                    .values(
                        "current_power",
                        "current_voltage",
                        "current_amperage",
                    )
                )

                for reading in readings:

                    stats["total_power"] += float(
                        reading["current_power"] or 0
                    )

                    stats["total_voltage"] += float(
                        reading["current_voltage"] or 0
                    )

                    stats["total_amperage"] += float(
                        reading["current_amperage"] or 0
                    )

        # --------------------------------------------------------
        # Sort participants.
        #
        # Ranking is based on total riding duration.
        #
        # If two participants have the same duration, use
        # participant ID as a deterministic tie-breaker.
        # --------------------------------------------------------

        ranked_participants = sorted(
            participant_stats.values(),
            key=lambda item: (
                -item["total_power"],
                item["participant_id"],
            ),
        )

        # --------------------------------------------------------
        # Top 10
        # --------------------------------------------------------

        top_10 = ranked_participants[:10]

        results = []

        for index, participant in enumerate(
            top_10,
            start=1,
        ):

            results.append(
                {
                    "rank": index,
                    "participant_id": (
                        participant["participant_id"]
                    ),
                    "participant_name": (
                        participant["participant_name"]
                    ),
                    "total_duration_seconds": round(
                        participant[
                            "total_duration_seconds"
                        ],
                        2,
                    ),
                    "total_voltage": round(
                        participant["total_voltage"],
                        2,
                    ),
                    "total_power": round(
                        participant["total_power"],
                        2,
                    ),
                    "total_amperage": round(
                        participant["total_amperage"],
                        2,
                    ),
                }
            )

        # --------------------------------------------------------
        # Response
        # --------------------------------------------------------

        return Response(
            {
                "status": True,
                "cycle": {
                    "id": cycle.id,
                    "cycle_no": cycle.cycle_no,
                    "controller_no": cycle.controller_no,
                },
                "data": results,
            },
            status=status.HTTP_200_OK,
        )




# ================================================================
# DELETE CYCLE RIDE SESSION
# ================================================================

class CycleRideSessionDeleteAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @transaction.atomic
    def delete(self, request, cycle_id, session_id):
        # --------------------------------------------------------
        # Make sure the cycle exists.
        # --------------------------------------------------------

        try:
            cycle = Cycle.objects.get(pk=cycle_id)
        except Cycle.DoesNotExist:
            return Response(
                {
                    "status": False,
                    "message": "Cycle not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # --------------------------------------------------------
        # IMPORTANT:
        # Filter by BOTH cycle and session ID.
        #
        # This prevents deleting a session belonging to another
        # cycle.
        # --------------------------------------------------------

        try:
            session = (
                CycleRideSession.objects
                .select_for_update()
                .select_related("participant")
                .get(
                    pk=session_id,
                    cycle=cycle,
                )
            )
        except CycleRideSession.DoesNotExist:
            return Response(
                {
                    "status": False,
                    "message": "Session not found in this cycle.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # --------------------------------------------------------
        # Never delete a running or paused session.
        # --------------------------------------------------------

        if session.is_active or session.is_paused:
            return Response(
                {
                    "status": False,
                    "message": "End the session before deleting it.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # --------------------------------------------------------
        # Collect the session's segments BEFORE deleting the
        # session.
        #
        # PowerMonitor does not have a direct FK to CycleRideSession,
        # so we need the segment time ranges to identify the
        # corresponding readings.
        # --------------------------------------------------------

        segments = list(
            CycleRideSegment.objects
            .filter(session=session)
            .order_by("started_at")
        )

        participant_id = session.participant_id
        allocation_id = (
            ParticipentCycle.objects
            .filter(
                cycle=cycle,
            )
            .values_list("id", flat=True)
            .first()
        )

        # --------------------------------------------------------
        # Delete PowerMonitor readings belonging to this session.
        #
        # They are identified by:
        #   - this participant
        #   - this cycle allocation
        #   - each session segment's time range
        #
        # This avoids deleting readings belonging to another
        # participant/session.
        # --------------------------------------------------------

        deleted_readings = 0

        if allocation_id and segments:
            for segment in segments:
                segment_end = segment.ended_at

                if segment_end is None:
                    # A non-ended segment should normally not exist
                    # because active/paused sessions are blocked above.
                    # Use now only as a safety fallback.
                    segment_end = timezone.now()

                deleted_count, _ = (
                    PowerMonitor.objects
                    .filter(
                        participent_id=allocation_id,
                        participant_data_id=participant_id,
                        updated_at__gte=segment.started_at,
                        updated_at__lte=segment_end,
                    )
                    .delete()
                )

                deleted_readings += deleted_count

        # --------------------------------------------------------
        # Delete the session.
        #
        # CycleRideSegment is CASCADE, so its child segments are
        # deleted automatically.
        # --------------------------------------------------------

        session.delete()

        return Response(
            {
                "status": True,
                "message": "Session deleted.",
                "data": {
                    "deleted_count": 1,
                },
            },
            status=status.HTTP_200_OK,
        )


# ================================================================
# BULK DELETE CYCLE RIDE SESSIONS
# ================================================================

class CycleRideSessionBulkDeleteAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @transaction.atomic
    def post(self, request, cycle_id):
        # --------------------------------------------------------
        # Validate cycle.
        # --------------------------------------------------------

        try:
            cycle = Cycle.objects.get(pk=cycle_id)
        except Cycle.DoesNotExist:
            return Response(
                {
                    "status": False,
                    "message": "Cycle not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # --------------------------------------------------------
        # Input:
        #
        # Option A:
        # {
        #     "participant_id": 12
        # }
        #
        # Option B:
        # {
        #     "session_ids": ["uuid1", "uuid2"]
        # }
        #
        # Supporting both keeps the endpoint flexible.
        # --------------------------------------------------------

        participant_id = request.data.get("participant_id")
        session_ids = request.data.get("session_ids")

        if participant_id in ("", None) and not session_ids:
            return Response(
                {
                    "status": False,
                    "message": (
                        "participant_id or session_ids is required."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --------------------------------------------------------
        # Build the target queryset.
        # --------------------------------------------------------

        sessions = (
            CycleRideSession.objects
            .select_for_update()
            .select_related("participant")
            .filter(cycle=cycle)
        )

        if participant_id not in ("", None):
            try:
                participant_id = int(participant_id)
            except (TypeError, ValueError):
                return Response(
                    {
                        "status": False,
                        "message": "Invalid participant_id.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            sessions = sessions.filter(
                participant_id=participant_id,
            )

        elif session_ids:
            if not isinstance(session_ids, list):
                return Response(
                    {
                        "status": False,
                        "message": "session_ids must be a list.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not session_ids:
                return Response(
                    {
                        "status": False,
                        "message": "session_ids cannot be empty.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            sessions = sessions.filter(
                id__in=session_ids,
            )

        sessions = list(
            sessions.order_by(
                "started_at",
                "created_at",
            )
        )

        # --------------------------------------------------------
        # Nothing matched.
        # --------------------------------------------------------

        if not sessions:
            return Response(
                {
                    "status": False,
                    "message": "No sessions found to delete.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # --------------------------------------------------------
        # CRITICAL:
        #
        # Check EVERY session before deleting ANY session.
        #
        # Because this entire method is atomic, returning here
        # means nothing will be deleted.
        # --------------------------------------------------------

        for session in sessions:
            if session.is_active or session.is_paused:
                return Response(
                    {
                        "status": False,
                        "message": (
                            "End the session before deleting it."
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        # --------------------------------------------------------
        # Find the cycle allocation once.
        # --------------------------------------------------------

        allocation_id = (
            ParticipentCycle.objects
            .filter(cycle=cycle)
            .values_list("id", flat=True)
            .first()
        )

        # --------------------------------------------------------
        # Delete PowerMonitor readings belonging to each session.
        # --------------------------------------------------------

        if allocation_id:
            for session in sessions:
                segments = list(
                    CycleRideSegment.objects
                    .filter(session=session)
                    .order_by("started_at")
                )

                for segment in segments:
                    segment_end = segment.ended_at

                    if segment_end is None:
                        segment_end = timezone.now()

                    PowerMonitor.objects.filter(
                        participent_id=allocation_id,
                        participant_data_id=session.participant_id,
                        updated_at__gte=segment.started_at,
                        updated_at__lte=segment_end,
                    ).delete()

        # --------------------------------------------------------
        # Delete all sessions.
        #
        # CycleRideSegment rows are deleted by CASCADE.
        # --------------------------------------------------------

        deleted_count = len(sessions)

        for session in sessions:
            session.delete()

        return Response(
            {
                "status": True,
                "message": (
                    f"{deleted_count} session"
                    f"{'s' if deleted_count != 1 else ''} deleted."
                ),
                "data": {
                    "deleted_count": deleted_count,
                },
            },
            status=status.HTTP_200_OK,
        )