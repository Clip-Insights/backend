from django.contrib import admin
from .models import AnalyticsData
from datetime import timedelta, date
import json

@admin.register(AnalyticsData)
class AnalyticsDataAdmin(admin.ModelAdmin):
    change_list_template = "admin/analytics_chart.html"
    list_display = ("date", "page_views", "active_users", "new_users", "sessions", "avg_session_duration", "bounce_rate")

    def changelist_view(self, request, extra_context=None):
        today = date.today()
        last_7_days = [today - timedelta(days=i) for i in reversed(range(7))]

        data = AnalyticsData.objects.filter(date__in=last_7_days).order_by("date")

        labels = [d.date.strftime("%Y-%m-%d") for d in data]
        page_views = [d.page_views for d in data]
        active_users = [d.active_users for d in data]
        new_users = [d.new_users for d in data]
        sessions = [d.sessions for d in data]

        extra_context = extra_context or {}
        extra_context["labels"] = json.dumps(labels)
        extra_context["page_views"] = json.dumps(page_views)
        extra_context["active_users"] = json.dumps(active_users)
        extra_context["new_users"] = json.dumps(new_users)
        extra_context["sessions"] = json.dumps(sessions)

        return super().changelist_view(request, extra_context=extra_context)
