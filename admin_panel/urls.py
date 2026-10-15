from django.urls import path
from .views import *
from .views import LoginAPIView, LogoutAPIView
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    CycleHistoryAPIView,
    CycleRideSessionDeleteAPIView,
    CycleRideSessionBulkDeleteAPIView,
    CycleHistoryTop10APIView
)
urlpatterns = [

    # ===========================
    # Cycle CRUD
    # ===========================
    path(
        "cycles/",
        CycleAPIView.as_view(),
        name="cycle-list-create",
    ),
    path(
        "cycles/<int:pk>/",
        CycleAPIView.as_view(),
        name="cycle-detail",
    ),

    # ===========================
    # Participant CRUD
    # ===========================
    path(
        "participants/",
        ParticipentAPIView.as_view(),
        name="participant-list-create",
    ),
    path(
        "cycles/available/",
        Available_Cycle.as_view(),
        # name="participant-list-create",
    ),
    path(
        "participants/available/",
        AvailableParticipant.as_view(),
        # name="participant-list-create",
    ),
    path(
        "participants/create-and-allocate/",
        CreateAndAllocateParticipantAPIView.as_view(),
        name="participant-create-and-allocate",
    ),
    path(
        "participants/<int:pk>/",
        ParticipentAPIView.as_view(),
        name="participant-detail",
    ),

    # ===========================
    # Participant Cycle Allocation CRUD
    # ===========================
    path(
        "participant-cycles/",
        ParticipentCycleAPIView.as_view(),
        name="participant-cycle-list-create",
    ),
    path(
        "participant-cycles-duration/",
        ParticipentCycleDurationAPIView.as_view(),
        name="participant-cycle-list-duration-create",
    ),
    path(
        "participant-cycles/<int:pk>/",
        ParticipentCycleAPIView.as_view(),
        name="participant-cycle-detail",
    ),

    # ===========================
    # Screen CRUD
    # ===========================
    path(
        "screens/",
        ScreenAPIView.as_view(),
        name="screen-list-create",
    ),
    path(
        "screens/<int:pk>/",
        ScreenAPIView.as_view(),
        name="screen-detail",
    ),
    path(
        "login/",
        LoginAPIView.as_view(),
        name="login",
    ),

    path(
        "logout/",
        LogoutAPIView.as_view(),
        name="logout",
    ),

    path(
        "refresh/",
        TokenRefreshView.as_view(),
        name="refresh",
    ),
    path(
        "free-text/",
        LastFreeTextApiView.as_view(),
        name="free-text",
    ),
    path(
    "free-text/draft/",
    FreeTextDraftAPIView.as_view(),
    name="free-text-draft",
    ),

    path(
        "free-text/history/",
        FreeTextHistoryAPIView.as_view(),
        name="free-text-history",
    ),

    path(
        "free-text/history/<int:pk>/",
        FreeTextHistoryDetailAPIView.as_view(),
        name="free-text-history-detail",
    ),
    path(
        "app-theme/",
        AppThemeAPIView.as_view(),
        name="app-theme",
    ),
    path(
        "app-theme-list/",
        AppThemeListAPIViews.as_view(),
        name="app-theme",
    ),
    path(
        "cycle-history/",
        CycleHistoryAPIView.as_view(),
        name="cycle-history",
    ),

    path(
        "cycle-history/<int:cycle_id>/",
        CycleHistoryAPIView.as_view(),
        name="cycle-history-detail",
    ),
        # Delete one session
    path(
        "cycle-history/<int:cycle_id>/sessions/<uuid:session_id>/",
        CycleRideSessionDeleteAPIView.as_view(),
    ),

    # Delete participant's sessions
    path(
        "cycle-history/<int:cycle_id>/sessions/bulk-delete/",
        CycleRideSessionBulkDeleteAPIView.as_view(),
    ),
    path(
        "cycle-history/<int:cycle_id>/top-10/",
        CycleHistoryTop10APIView.as_view(),
        name="cycle-history-top-10",
    ),
]