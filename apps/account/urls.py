from django.urls import path
from . import views

urlpatterns = [
    path("sendCode", views.send_code),
    path("login", views.login),
    path("register", views.register),
    path("loginByPassword", views.login_by_password),
    path("resetPassword", views.reset_password),
    path("changePassword", views.change_password),
    path("changePhone", views.change_phone),
    path("me", views.me),
    path("location", views.user_location),
    path("updateProfile", views.update_profile),
    path("privacy", views.privacy_settings),
    path("wallet/balance", views.wallet_balance),
    path("wallet/log", views.wallet_log_list),
    path("orders", views.order_list),
    path("withdraw/apply", views.withdraw_apply),
    path("teacher/apply", views.teacher_apply),
    path("teacher/status", views.teacher_status),
]
