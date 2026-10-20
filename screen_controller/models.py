from django.db import models
from django.forms import IntegerField


class Screen(models.Model):
    name = models.CharField(max_length=100)
    path = models.CharField(max_length=200)

    thumbnail = models.ImageField(
        upload_to="screen_thumbnails/",
        blank=True,
        null=True,
    )

    is_live = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f'{self.name} {self.id}'


class ScreenPosition(models.Model):
    name = models.CharField(max_length=200, default="")
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)

    width = models.IntegerField(default=1200)
    height = models.IntegerField(default=900)

    fullscreen = models.BooleanField(default=False)
    always_on_top = models.BooleanField(default=False)
    resizable = models.BooleanField(default=True)
    movable = models.BooleanField(default=True)
    minimizable = models.BooleanField(default=True)
    maximizable = models.BooleanField(default=True)

    visible = models.BooleanField(default=True)

    menu_bar_visible = models.BooleanField(default=False)
    auto_hide_menu_bar = models.BooleanField(default=True)

    opacity = models.FloatField(default=1.0)

    def __str__(self):
        return self.name or f"Position {self.id}"


class Windows(models.Model):
    name = models.CharField(max_length=200)
    position = models.ForeignKey(
        ScreenPosition,
        on_delete=models.CASCADE,
        related_name="windows",
    )
    activee_screen = models.ForeignKey(
        Screen,
        on_delete=models.CASCADE,
        related_name="windows",
    )
    is_active = models.BooleanField(default=True)
    pid = models.IntegerField(default=0)
    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name}  {self.id}"
