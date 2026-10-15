from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from .forms import CycleForm, ParticipentForm, AllocateForm
from .models import Cycle, Participent, ParticipentCycle
from django.contrib import messages
from django.db import IntegrityError
from .cache_utils import get_dashboard_context, invalidate_dashboard_cache

def home(request):
    return render(request, 'home.html', {'title': 'Electricity Monitoring'})


def login_view(request):
    return auth_views.LoginView.as_view(template_name='registration/login.html')(request)


@login_required
def dashboard(request):
    context = get_dashboard_context()
    return render(request, 'dashboard.html', context)


@login_required
def register_cycle(request):
    if request.method == 'POST':
        form = CycleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = CycleForm()

    return render(request, 'cycle_form.html', {'form': form})


@login_required
def register_participent(request):
    if request.method == 'POST':
        form = ParticipentForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            invalidate_dashboard_cache()
            return redirect('dashboard')
    else:
        form = ParticipentForm()
    return render(request, 'participent_form.html', {'form': form})


@login_required
def allocate_cycle(request):
    if request.method == 'POST':
        form = AllocateForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                invalidate_dashboard_cache()
                messages.success(request, "Cycle allocated successfully.")
                return redirect('dashboard')
            except IntegrityError:
                messages.error(
                    request,
                    "This participant has already been allocated to this cycle."
                )
    else:
        form = AllocateForm()

    return render(request, 'allocate_form.html', {'form': form})


