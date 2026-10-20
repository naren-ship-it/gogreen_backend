from django.urls import path
from .views import *

urlpatterns = [
    path('participant/',ParticipantExcel.as_view())

]