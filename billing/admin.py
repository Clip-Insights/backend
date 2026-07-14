from django.contrib import admin

from billing.models import PaddlePlanMap, Subscription


@admin.register(PaddlePlanMap)
class PaddlePlanMapAdmin(admin.ModelAdmin):
    list_display = ("plan", "annual_price_usd", "paddle_product_id",
                    "paddle_price_id_monthly", "paddle_price_id_annual")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "billing_cycle", "current_period_end", "cancel_at_period_end")
    list_filter = ("status", "plan")
    search_fields = ("user__email", "paddle_subscription_id")
