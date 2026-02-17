from django.urls import path
from . import views

urlpatterns = [
    path("paipan", views.bazi_paipan),
    path("bazi/status", views.bazi_status),
    path("today-fortune", views.today_fortune),
    path("birth-match", views.birth_match_list),
    path("xiyongshen", views.xiyongshen_get),
    path("xiyongshen-match", views.xiyongshen_match),
    path("fate-match", views.fate_match),
    path("fengshui", views.fengshui_analyze),
    path("ai-master-chat/history", views.ai_master_chat_history),
    path("ai-master-chat/new", views.ai_master_chat_new),
    path("ai-master-chat", views.ai_master_chat),
    path("constitution-questions", views.constitution_questions),
    path("constitution-test", views.constitution_test),
]
