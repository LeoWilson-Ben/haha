from django.urls import path
from . import views

urlpatterns = [
    path("join", views.room_join),
    path("leave", views.room_leave),
]
