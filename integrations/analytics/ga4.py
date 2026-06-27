from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
from google.oauth2 import service_account
from django.conf import settings

from analytics.models import AnalyticsData


class GA4AnalyticsFetcher:
    def fetch_and_store(self) -> None:
        credentials = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_CREDENTIALS_JSON
        )
        client = BetaAnalyticsDataClient(credentials=credentials)

        request = RunReportRequest(
            property=f"properties/{settings.GOOGLE_ANALYTICS_PROPERTY_ID}",
            dimensions=[Dimension(name="date")],
            metrics=[
                Metric(name="screenPageViews"),
                Metric(name="activeUsers"),
                Metric(name="newUsers"),
                Metric(name="sessions"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate"),
            ],
            date_ranges=[DateRange(start_date="7daysAgo", end_date="today")],
        )

        response = client.run_report(request)

        for row in response.rows:
            date_str = row.dimension_values[0].value
            AnalyticsData.objects.update_or_create(
                date=date_str,
                defaults={
                    "page_views": int(row.metric_values[0].value),
                    "active_users": int(row.metric_values[1].value),
                    "new_users": int(row.metric_values[2].value),
                    "sessions": int(row.metric_values[3].value),
                    "avg_session_duration": float(row.metric_values[4].value),
                    "bounce_rate": float(row.metric_values[5].value),
                },
            )
