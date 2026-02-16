from django.urls import path
from . import views

urlpatterns = [
    path("banners", views.banners),
    path("upload", views.upload),
    path("ipLocation", views.ip_location),
]
