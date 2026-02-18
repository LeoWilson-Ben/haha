from django.urls import path
from . import views

urlpatterns = [
    path("conversations", views.conversation_list),
    path("conversation/single", views.get_or_create_single),
    path("conversation/single-with-master", views.get_or_create_single_with_master),
    path("conversation/group", views.create_group),
    path("conversation/<int:conversation_id>/messages", views.message_list),
    path("conversation/<int:conversation_id>/message", views.send_message),
    path("conversation/<int:conversation_id>/members", views.group_members),
    path("conversation/<int:conversation_id>/info", views.group_info),
    path("conversation/<int:conversation_id>", views.update_group),
    path("conversation/<int:conversation_id>/add-members", views.add_members),
    path("conversation/<int:conversation_id>/kick", views.kick_member),
    path("conversation/<int:conversation_id>/read", views.mark_read),
    path("chat/applies", views.chat_apply_list),
    path("chat/apply", views.send_chat_apply),
    path("chat/apply/<int:apply_id>/approve", views.approve_chat_apply),
    path("chat/apply/<int:apply_id>/reject", views.reject_chat_apply),
    path("groups/joinable", views.joinable_groups),
    path("group/<int:conversation_id>/apply", views.apply_join_group),
    path("group/join-applies", views.group_join_apply_list),
    path("group/join-apply/<int:apply_id>/approve", views.approve_group_join_apply),
    path("group/join-apply/<int:apply_id>/reject", views.reject_group_join_apply),
    path("conversations/master-consult", views.master_consult_list),
]
