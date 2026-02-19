# -*- coding: utf-8 -*-
from django.urls import path
from . import views

urlpatterns = [
    path("stats", views.dashboard_stats),
    path("core-data", views.core_data_board),
    path("teacher-applies", views.teacher_apply_list),
    path("teacher-applies/<int:apply_id>/approve", views.teacher_apply_approve),
    path("teacher-applies/<int:apply_id>/reject", views.teacher_apply_reject),
    path("teachers/<int:user_id>/consult-price", views.teacher_set_consult_price),
    path("posts", views.post_list),
    path("posts/<int:post_id>/status", views.post_set_status),
    path("reports", views.report_list),
    path("reports/<int:report_id>/handle", views.report_handle),
    path("withdraws", views.withdraw_list),
    path("withdraws/<int:withdraw_id>/approve", views.withdraw_approve),
    path("withdraws/<int:withdraw_id>/reject", views.withdraw_reject),
    path("users", views.user_list),
    path("users/<int:user_id>/status", views.user_set_status),
    path("users/<int:user_id>/delete", views.user_delete),
    path("ai-prompts", views.ai_prompt_list),
    path("ai-prompts/<str:key>", views.ai_prompt_get),
    path("ai-prompts/<str:key>/update", views.ai_prompt_update),
]
