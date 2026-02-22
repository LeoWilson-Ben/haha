from django.contrib import admin
from django.utils.html import format_html
from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "status_display",
        "sort_order",
        "start_at",
        "end_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("title", "content")
    list_editable = ("sort_order",)
    ordering = ("-sort_order", "-created_at")
    date_hierarchy = "created_at"
    list_per_page = 20

    fieldsets = (
        (None, {"fields": ("title", "content", "link_url")}),
        ("展示控制", {"fields": ("status", "sort_order", "start_at", "end_at")}),
    )

    def status_display(self, obj):
        if obj.status == 1:
            return format_html('<span style="color: green;">展示</span>')
        return format_html('<span style="color: gray;">下架</span>')

    status_display.short_description = "状态"
