from django.core.management.base import BaseCommand
from analytics.services import fetch_and_store_ga_data

class Command(BaseCommand):
    help = 'Fetch GA4 analytics data and store in the DB'

    def handle(self, *args, **kwargs):
        fetch_and_store_ga_data()
        self.stdout.write(self.style.SUCCESS('✅ GA data fetched and stored.'))
