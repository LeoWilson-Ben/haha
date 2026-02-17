from django.urls import path
from . import views

urlpatterns = [
    path("banners", views.banners),
    path("announcements", views.announcements),
    path("upload", views.upload),
    path("presign-upload", views.presign_upload),
    path("confirm-upload", views.confirm_upload),
    path("ipLocation", views.ip_location),
]
