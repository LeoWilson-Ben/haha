# 表由 sql/schema.sql 创建，managed=False
from django.db import models


class Conversation(models.Model):
    id = models.BigAutoField(primary_key=True)
    type = models.CharField(max_length=20)  # single / group
    name = models.CharField(max_length=128, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversation"
        managed = False


class ConversationMember(models.Model):
    id = models.BigAutoField(primary_key=True)
    conversation_id = models.BigIntegerField()
    user_id = models.BigIntegerField()
    role = models.CharField(max_length=20, default="member")
    mute = models.SmallIntegerField(default=0)
    top = models.SmallIntegerField(default=0)
    last_read_msg_id = models.BigIntegerField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conversation_member"
        managed = False


class Message(models.Model):
    id = models.BigAutoField(primary_key=True)
    conversation_id = models.BigIntegerField()
    sender_id = models.BigIntegerField()
    type = models.CharField(max_length=20)  # text / image / voice
    content_encrypted = models.TextField(null=True, blank=True)
    extra_json = models.TextField(null=True, blank=True)
    status = models.SmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message"
        managed = False


class ChatApply(models.Model):
    id = models.BigAutoField(primary_key=True)
    from_user_id = models.BigIntegerField()
    to_user_id = models.BigIntegerField()
    status = models.CharField(max_length=20, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "chat_apply"
        managed = False


class ImGroup(models.Model):
    """群聊扩展：conversation type=group 时对应一行"""
    conversation_id = models.BigIntegerField(primary_key=True)
    owner_id = models.BigIntegerField()
    max_members = models.IntegerField(default=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "im_group"
        managed = False
