from django.db import models


class VoiceRoom(models.Model):
    """语音匹配房间，对应 voice_room 表"""
    id = models.BigAutoField(primary_key=True)
    room_id = models.CharField(max_length=64, db_column="room_id")
    user_id_1 = models.BigIntegerField()
    user_id_2 = models.BigIntegerField()
    rtc_channel = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default="ongoing")
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "voice_room"
        managed = False
