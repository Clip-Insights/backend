# analytics/models.py

from django.db import models

class AnalyticsData(models.Model):
    date = models.DateField(unique=True)
    page_views = models.IntegerField()
    active_users = models.IntegerField()
    new_users = models.IntegerField()
    sessions = models.IntegerField()
    avg_session_duration = models.FloatField()
    bounce_rate = models.FloatField()

    def __str__(self):
        return f"Analytics on {self.date}"
