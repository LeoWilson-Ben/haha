from django.urls import path
from . import views

urlpatterns = [
    path("join", views.join_pool),
    path("cancel", views.cancel_match),
    path("status", views.match_status),
]
