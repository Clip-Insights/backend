"""Seed the plan catalog and (optionally) create the matching Paddle
products/prices, storing their ids back on the Plan rows.

Idempotent: plan quotas/prices are refreshed from the catalog, existing Paddle
ids are kept, and only missing Paddle objects are created.

    uv run python manage.py setup_billing            # seed + sync to Paddle
    uv run python manage.py setup_billing --no-paddle  # seed plans only
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from billing.models import Plan
from billing.services import PLAN_CATALOG
from integrations.registry import get_payment


class Command(BaseCommand):
    help = "Seed subscription plans and sync them to Paddle (products + prices)."

    def add_arguments(self, parser):
        parser.add_argument("--no-paddle", action="store_true", help="Seed plans without calling Paddle.")

    def handle(self, *args, **options):
        for entry in PLAN_CATALOG:
            entry = dict(entry)
            code = entry.pop("code")
            entry["price_monthly_usd"] = Decimal(entry["price_monthly_usd"])
            entry["price_annual_usd"] = Decimal(entry["price_annual_usd"])
            plan, created = Plan.objects.update_or_create(code=code, defaults=entry)
            self.stdout.write(f"{'Created' if created else 'Updated'} plan: {plan.name}")

        if options["no_paddle"]:
            self.stdout.write(self.style.SUCCESS("Plans seeded (Paddle sync skipped)."))
            return

        payment = get_payment()
        for plan in Plan.objects.exclude(code="free"):
            if not plan.paddle_product_id:
                plan.paddle_product_id = payment.create_product(
                    name=f"Clip Insights {plan.name}",
                    description=f"Clip Insights {plan.name} subscription",
                )
                self.stdout.write(f"  Paddle product for {plan.code}: {plan.paddle_product_id}")
            if not plan.paddle_price_id_monthly and plan.price_monthly_usd > 0:
                plan.paddle_price_id_monthly = payment.create_price(
                    plan.paddle_product_id,
                    int(plan.price_monthly_usd * 100),
                    "month",
                    f"{plan.name} monthly",
                )
                self.stdout.write(f"  Monthly price for {plan.code}: {plan.paddle_price_id_monthly}")
            if not plan.paddle_price_id_annual and plan.price_annual_usd > 0:
                plan.paddle_price_id_annual = payment.create_price(
                    plan.paddle_product_id,
                    int(plan.price_annual_usd * 100),
                    "year",
                    f"{plan.name} annual",
                )
                self.stdout.write(f"  Annual price for {plan.code}: {plan.paddle_price_id_annual}")
            plan.save()

        self.stdout.write(self.style.SUCCESS("Plans seeded and synced to Paddle."))
