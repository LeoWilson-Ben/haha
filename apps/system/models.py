from django.db import models


class Banner(models.Model):
    id = models.BigAutoField(primary_key=True)
    type = models.CharField(max_length=20)  # home / splash
    image_url = models.CharField(max_length=512)
    link_url = models.CharField(max_length=512, null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    status = models.SmallIntegerField(default=1)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "banner"
        managed = False
