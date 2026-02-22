# 表由 sql/schema.sql 创建，managed=False
from django.db import models


class Topic(models.Model):
    name = models.CharField(max_length=64)
    cover_url = models.CharField(max_length=512, null=True, blank=True)
    description = models.CharField(max_length=500, null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    heat_score = models.IntegerField(default=0)
    status = models.SmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "topic"
        managed = False


class Post(models.Model):
    user_id = models.BigIntegerField()
    content = models.TextField(null=True, blank=True)
    media_type = models.CharField(max_length=20, default="image_text")
    media_urls_json = models.TextField(null=True, blank=True)
    media_cover_urls_json = models.TextField(null=True, blank=True)  # 视频封面 URL 列表 JSON，与 media_urls 对应
    topic_ids_json = models.CharField(max_length=500, null=True, blank=True)
    tags_json = models.CharField(max_length=500, null=True, blank=True)  # 自定义标签名 JSON 数组
    location_code = models.CharField(max_length=32, null=True, blank=True)
    visibility = models.SmallIntegerField(default=1)
    allow_comment = models.SmallIntegerField(default=1)
    status = models.SmallIntegerField(default=1)
    like_count = models.IntegerField(default=0)
    comment_count = models.IntegerField(default=0)
    share_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "post"
        managed = False


class Comment(models.Model):
    post_id = models.BigIntegerField()
    user_id = models.BigIntegerField()
    parent_id = models.BigIntegerField(null=True, blank=True)
    content = models.TextField()
    status = models.SmallIntegerField(default=1)
    like_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "comment"
        managed = False


class PostLike(models.Model):
    """联合主键 (user_id, post_id)，表无 id 列。user_id 设 primary_key 仅为避免 Django 生成 id。"""
    user_id = models.BigIntegerField(primary_key=True)
    post_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "post_like"
        managed = False


class PostFavorite(models.Model):
    """联合主键 (user_id, post_id)，表无 id 列。"""
    user_id = models.BigIntegerField(primary_key=True)
    post_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "post_favorite"
        managed = False


class UserFollow(models.Model):
    """联合主键 (user_id, target_user_id)，表无 id 列。"""
    user_id = models.BigIntegerField(primary_key=True)
    target_user_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_follow"
        managed = False


class Notification(models.Model):
    """互动通知：被评论、点赞、收藏、分享"""
    user_id = models.BigIntegerField()
    type = models.CharField(max_length=20)  # comment / like / favorite / share
    from_user_id = models.BigIntegerField()
    post_id = models.BigIntegerField()
    comment_id = models.BigIntegerField(null=True, blank=True)
    content_snippet = models.CharField(max_length=255, null=True, blank=True)
    read = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification"
        managed = False


class SystemNotification(models.Model):
    """系统通知：公告、帖子下架等，在消息-通知中展示"""
    user_id = models.BigIntegerField()
    type = models.CharField(max_length=32)  # announcement / post_removed
    title = models.CharField(max_length=255)
    content = models.TextField(null=True, blank=True)
    extra_json = models.CharField(max_length=1024, null=True, blank=True)
    read = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "system_notification"
        managed = False


class Report(models.Model):
    id = models.BigAutoField(primary_key=True)
    reporter_id = models.BigIntegerField()
    target_type = models.CharField(max_length=20)
    target_id = models.BigIntegerField()
    reason = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=20, default="pending")
    handle_result = models.CharField(max_length=255, null=True, blank=True)
    handled_by = models.BigIntegerField(null=True, blank=True)
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "report"
        managed = False
