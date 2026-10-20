from django.shortcuts import get_object_or_404, redirect
from .models import Screen
from django.shortcuts import render

def screens(request):
    # Show the page; you can also list existing screens here
    screens_qs = Screen.objects.all()
    return render(request, 'screens.html', {
        'title': 'Electricity Monitoring',
        'screens': screens_qs,
    })

def create_screen(request):
    if request.method == "POST":
        Screen.objects.create(
            name=request.POST["name"],
            path=request.POST["path"],
            thumbnail=request.FILES.get("thumbnail"),
        )
        # notify websocket clients here
    return redirect("screens")


def update_screen(request, screen_id):
    screen = get_object_or_404(Screen, id=screen_id)

    if request.method == "POST":
        screen.name = request.POST["name"]
        screen.path = request.POST["path"]

        if "thumbnail" in request.FILES:
            screen.thumbnail = request.FILES["thumbnail"]

        screen.save()
        # notify websocket clients here

    return redirect("screens")


def delete_screen(request, screen_id):
    screen = get_object_or_404(Screen, id=screen_id)

    if request.method == "POST":
        screen.delete()
        # notify websocket clients here

    return redirect("screens")


def set_current_screen(request, screen_id):
    if request.method == "POST":
        Screen.objects.update(is_live=False)

        screen = get_object_or_404(Screen, id=screen_id)
        screen.is_live = True
        screen.save()

        # notify websocket clients here

    return redirect("screens")

