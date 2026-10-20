from django.apps import AppConfig


class CoreAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.db.models.signals import post_migrate

        import core.signals

        receivers = [
            (create_default_superuser, "core_create_default_superuser"),
            (create_app_theme, "core_create_app_theme"),
            (screen_lists, "core_screen_lists"),
            (screen_position, "core_screen_position"),
            (create_group_participant, "core_create_group_participant"),
            (create_free_text, "core_create_free_text"),
            (create_default_window, "core_create_default_window"),
        ]

        for receiver, uid in receivers:
            post_migrate.connect(
                receiver,
                sender=self,
                dispatch_uid=uid,
            )


# --------------------------------------------------
# DEFAULT SUPERUSER
# --------------------------------------------------

def create_default_superuser(sender, **kwargs):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    username = "admin"
    password = "Admin@123"

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
        },
    )

    if created:
        user.set_password(password)
        user.save(update_fields=["password"])

    print(
        f"[DEBUG] Admin user ID={user.pk}, "
        f"created={created}"
    )


# --------------------------------------------------
# DEFAULT APP THEME
# --------------------------------------------------

def create_app_theme(sender, **kwargs):
    from .models import AppTheme

    print("[DEBUG] Checking default app theme...")

    themes = AppTheme.objects.filter(
        name="Default",
        is_active=True,
    ).order_by("id")

    theme = themes.first()
    created = False

    if theme is None:
        theme = AppTheme.objects.create(
            name="Default",
            is_active=True,
        )
        created = True

    duplicate_ids = list(
        AppTheme.objects.filter(
            name="Default",
            is_active=True,
        )
        .exclude(pk=theme.pk)
        .values_list("id", flat=True)
    )

    print(
        f"[DEBUG] Default theme ID={theme.pk}, "
        f"created={created}"
    )

    if duplicate_ids:
        print(
            f"[WARNING] Duplicate active default theme IDs: "
            f"{duplicate_ids}"
        )


# --------------------------------------------------
# DEFAULT SCREENS
# --------------------------------------------------

def screen_lists(sender, **kwargs):
    from screen_controller.models import Screen

    screens = [
        {"name": "Default Screen", "path": "/", "is_live": True},
        {"name": "Welcome Screen", "path": "/welcome", "is_live": False},
        {"name": "Individual Ranking Screen", "path": "/individual", "is_live": False},
        {"name": "Group Ranking Screen", "path": "/group-participants", "is_live": False},
        {"name": "Line Graph Screen", "path": "/player-analysis", "is_live": False},
        {"name": "Free Text Screen", "path": "/free-text", "is_live": False},
        {"name": "Participant Screen", "path": "/participants", "is_live": False},
        {"name": "Barchart Screen", "path": "/live-barchart", "is_live": False},
        {"name": "Combined View", "path": "/combined-view", "is_live": False},
        {"name": "Leaders Screen", "path": "/participant-rank", "is_live": False},
    ]

    for item in screens:
        screen, created = Screen.objects.get_or_create(
            path=item["path"],
            defaults={
                "name": item["name"],
                "is_live": item["is_live"],
            },
        )

        print(
            f"[DEBUG] Screen ID={screen.pk}, "
            f"name={screen.name}, path={screen.path}, "
            f"created={created}"
        )


# --------------------------------------------------
# DEFAULT SCREEN POSITION
# --------------------------------------------------

def screen_position(sender, **kwargs):
    from screen_controller.models import ScreenPosition

    positions = ScreenPosition.objects.filter(
        name="Default Position"
    ).order_by("id")

    position = positions.first()
    created = False

    if position is None:
        position = ScreenPosition.objects.create(
            name="Default Position",
            width=1920,
            height=1080,
            x=1920,
            y=0,
        )
        created = True

    duplicate_ids = list(
        ScreenPosition.objects.filter(
            name="Default Position"
        )
        .exclude(pk=position.pk)
        .values_list("id", flat=True)
    )

    print(
        f"[DEBUG] Default position ID={position.pk}, "
        f"created={created}"
    )

    if duplicate_ids:
        print(
            f"[WARNING] Duplicate default position IDs: "
            f"{duplicate_ids}"
        )


# --------------------------------------------------
# DEFAULT GROUPS AND PARTICIPANTS
# --------------------------------------------------

def create_group_participant(sender, **kwargs):
    from .models import Group, ParticipentCycle

    participants = list(
        ParticipentCycle.objects.all().order_by("id")
    )

    max_participants = 3
    total_groups = 4

    for group_number in range(1, total_groups + 1):
        group_name = f"Group {group_number}"

        group, created = Group.objects.get_or_create(
            name=group_name
        )

        start = (group_number - 1) * max_participants
        current_participants = participants[
            start:start + max_participants
        ]

        # Match the original behavior: assign up to three
        # participants per group and replace existing membership.
        if participants:
            group.members.set(current_participants)

        print(
            f"[DEBUG] {group_name}: "
            f"participant IDs={[p.pk for p in current_participants]}, "
            f"group_created={created}"
        )


# --------------------------------------------------
# DEFAULT FREE TEXT
# --------------------------------------------------

def create_free_text(sender, **kwargs):
    from admin_panel.models import FreeText

    text = "Welcome to GoGreen Cycle Pedaling Gamification"

    print("[DEBUG] Checking default free text...")

    # Use filter().first(), not get_or_create(), because
    # duplicate matching records already exist in the database.
    free_text = FreeText.objects.filter(
        text=text
    ).order_by("id").first()

    created = False

    if free_text is None:
        free_text = FreeText.objects.create(text=text)
        created = True

    duplicate_ids = list(
        FreeText.objects.filter(text=text)
        .exclude(pk=free_text.pk)
        .values_list("id", flat=True)
    )

    print(
        f"[DEBUG] FreeText ID={free_text.pk}, "
        f"created={created}, text={free_text.text}"
    )

    if duplicate_ids:
        print(
            f"[WARNING] Duplicate welcome FreeText IDs: "
            f"{duplicate_ids}"
        )


# --------------------------------------------------
# DEFAULT WINDOW
# --------------------------------------------------

def create_default_window(sender, **kwargs):
    from screen_controller.models import Screen, Windows, ScreenPosition

    print("[DEBUG] Starting create_default_window()")

    try:
        screen = Screen.objects.filter(
            path="/welcome"
        ).order_by("id").first()

        if screen is None:
            screen = Screen.objects.create(
                name="Welcome Screen",
                path="/welcome",
                is_live=False,
            )
            print(f"[DEBUG] Created welcome screen ID={screen.pk}")
        else:
            print(
                f"[DEBUG] Using welcome screen ID={screen.pk}"
            )

        position = ScreenPosition.objects.filter(
            name="Default Position"
        ).order_by("id").first()

        if position is None:
            position = ScreenPosition.objects.create(
                name="Default Position",
                width=1920,
                height=1080,
                x=1920,
                y=0,
            )
            print(f"[DEBUG] Created position ID={position.pk}")
        else:
            print(
                f"[DEBUG] Using default position ID={position.pk}"
            )

        # Reuse the existing default window if one exists.
        window = Windows.objects.filter(
            name="Default Window"
        ).order_by("id").first()

        created = False

        if window is None:
            window = Windows.objects.create(
                name="Default Window",
                position=position,
                activee_screen=screen,
            )
            created = True
        else:
            # Keep the existing window but ensure its references
            # point to the default screen and position.
            changed_fields = []

            if window.activee_screen_id != screen.pk:
                window.activee_screen = screen
                changed_fields.append("activee_screen")

            if window.position_id != position.pk:
                window.position = position
                changed_fields.append("position")

            if changed_fields:
                window.save(update_fields=changed_fields)

        print(
            f"[DEBUG] Window ID={window.pk}, "
            f"screen_id={window.activee_screen_id}, "
            f"position_id={window.position_id}, "
            f"created={created}"
        )

        duplicate_window_ids = list(
            Windows.objects.filter(name="Default Window")
            .exclude(pk=window.pk)
            .values_list("id", flat=True)
        )

        if duplicate_window_ids:
            print(
                f"[WARNING] Duplicate default window IDs: "
                f"{duplicate_window_ids}"
            )

        print("[DEBUG] create_default_window() completed successfully")
        return window

    except Exception as e:
        print(
            f"[ERROR] create_default_window failed: "
            f"{type(e).__name__}: {e}"
        )
        raise