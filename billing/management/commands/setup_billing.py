"""Create Paddle products/prices for every purchasable plan and store the ids
in PaddlePlanMap. The plan catalog itself is owned by the `plans` app (seeded
by its migrations, tuned in the admin) — this command only wires Paddle.

Idempotent: existing Paddle ids are kept; only missing objects are created.
Annual prices are sold at 10x monthly (two months free).

    uv run python manage.py setup_billing
"""
from django.core.management.base import BaseCommand

from billing.models import PaddlePlanMap
from integrations.registry import get_payment
from plans.models import Plan

ANNUAL_MONTHS = 10  # 12 months for the price of 10


class Command(BaseCommand):
    help = "Sync purchasable plans to Paddle (products + monthly/annual prices)."

    def handle(self, *args, **options):
        payment = get_payment()
        purchasable = Plan.objects.filter(is_active=True, monthly_price_usd__gt=0)
        if not purchasable.exists():
            self.stdout.write(self.style.WARNING("No purchasable plans found (run plans migrations first)."))
            return

        for plan in purchasable:
            mapping, _ = PaddlePlanMap.objects.get_or_create(plan=plan)
            annual_usd = plan.monthly_price_usd * ANNUAL_MONTHS
            if not mapping.paddle_product_id:
                mapping.paddle_product_id = payment.create_product(
                    name=f"Clip Insights {plan.name}",
                    description=plan.description or f"Clip Insights {plan.name} subscription",
                )
                self.stdout.write(f"  Paddle product for {plan.slug}: {mapping.paddle_product_id}")
            if not mapping.paddle_price_id_monthly:
                mapping.paddle_price_id_monthly = payment.create_price(
                    mapping.paddle_product_id,
                    int(plan.monthly_price_usd * 100),
                    "month",
                    f"{plan.name} monthly",
                )
                self.stdout.write(f"  Monthly price for {plan.slug}: {mapping.paddle_price_id_monthly}")
            if not mapping.paddle_price_id_annual:
                mapping.paddle_price_id_annual = payment.create_price(
                    mapping.paddle_product_id,
                    int(annual_usd * 100),
                    "year",
                    f"{plan.name} annual",
                )
                self.stdout.write(f"  Annual price for {plan.slug}: {mapping.paddle_price_id_annual}")
            mapping.annual_price_usd = annual_usd
            mapping.save()

        self.stdout.write(self.style.SUCCESS("Paddle catalog synced."))
