from django.apps import AppConfig


class CoreAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import core.signals

        from django.db.models.signals import post_migrate
        # post_migrate.connect(create_default_cycles, sender=self)
        post_migrate.connect(create_default_superuser, sender=self)
        post_migrate.connect(create_app_theme, sender=self)
        post_migrate.connect(screen_lists, sender=self)
        post_migrate.connect(screen_position, sender=self)
        post_migrate.connect(create_group_participant, sender=self)
        post_migrate.connect(create_free_text, sender=self)

# def create_default_cycles(sender, **kwargs):
#     from .models import Cycle

#     for i in range(1, 13):  # 1 to 12
#         Cycle.objects.get_or_create(
#             cycle_no=f"{i:02d}",       # 01, 02, ..., 12
#             controller_no=f"CTRL-{i}"  # CTRL-1, ..., CTRL-12
#         )


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
        user.save()



def create_app_theme(sender,**kwargs):
    from .models import AppTheme
    theme = AppTheme.objects.get_or_create(name="Default",is_active=True)


def screen_lists(sender, **kwargs):
    from screen_controller.models import Screen

    screens = [
        {"name": "Default Screen", "path": "/", "is_live": True},
        {"name": "Welcome Screen", "path": "/welcome", "is_live": False},
        {"name": "Individual Ranking Screen", "path": "/individual", "is_live": False},
        {"name": "Group Ranking Screen", "path": "/group-participants", "is_live": False},
        {"name": "Line Graph Screen", "path": "/player-analysis", "is_live": False},
        {"name": "Free Text Screen", "path": "/free-text", "is_live": False},
        {"name": "Participent Screen", "path": "/participants", "is_live": False},
        {"name": "Barchart Screen", "path": "/live-barchart", "is_live": False},
        {"name": "Combined View", "path" :"/combined-view", "is_live": False},
        {"name": "Leaders Screen", "path":"/participant-rank", "is_live": False},
    ]

    for i in screens:
        Screen.objects.get_or_create(
            path=i["path"],
            defaults={
                "name": i["name"],
                "is_live": i["is_live"],
            },
        )

def screen_position(sender,**kwargs):
    from screen_controller.models import ScreenPosition
    screen = ScreenPosition.objects.filter().first()
    if screen:
        pass
    else:
        screen = ScreenPosition.objects.get_or_create(
                width = 1920,
                height = 1080,
                x=1920
            )

def create_group_participant(sender, **kwargs):
    from .models import Group, ParticipentCycle

    participants = list(
        ParticipentCycle.objects.all().order_by("id")
    )

    max_participants = 3
    total_groups = 4

    if not participants:
        # No participants yet — just create empty groups 1 to 4
        for group_number in range(1, total_groups + 1):
            group_name = f"Group {group_number}"
            group, created = Group.objects.get_or_create(name=group_name)
        print("No participants found. Created Group 1 to Group 4 with no members.")
        return

    for group_number in range(1, total_groups + 1):
        group_name = f"Group {group_number}"

        group, created = Group.objects.get_or_create(
            name=group_name
        )

        index = (group_number - 1) * max_participants
        current_participants = participants[index:index + max_participants]

        # Clear existing members first
        group.members.clear()

        # Add participants (if any left for this group)
        if current_participants:
            group.members.add(*current_participants)

        print(
            f"{group_name}: "
            f"{[p.id for p in current_participants]}"
        )

        
def create_free_text(sender, **kwargs):
    from admin_panel.models import FreeText

    text = "Welcome to GoGreen Cycle Pedaling Gamification"

    FreeText.objects.create(text=text)