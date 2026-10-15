from django.db import models



class Screen(models.Model):
    name = models.CharField(max_length=100)
    path = models.CharField(max_length=200)

    thumbnail = models.ImageField(
        upload_to="screen_thumbnails/",
        blank=True,
        null=True,
    )

    is_live = models.BooleanField(default=False)

    # Window Position
    

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name

class ScreenPosition(models.Model):
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)

    # Window Size
    width = models.IntegerField(default=1200)
    height = models.IntegerField(default=900)

    # Window Behaviour
    fullscreen = models.BooleanField(default=False)
    always_on_top = models.BooleanField(default=False)
    resizable = models.BooleanField(default=True)
    movable = models.BooleanField(default=True)
    minimizable = models.BooleanField(default=True)
    maximizable = models.BooleanField(default=True)

    # Visibility
    visible = models.BooleanField(default=True)

    # Menu
    menu_bar_visible = models.BooleanField(default=False)
    auto_hide_menu_bar = models.BooleanField(default=True)

    # Appearance
    opacity = models.FloatField(default=1.0)