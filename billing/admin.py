from django.contrib import admin

from billing.models import Plan, Subscription, UsagePeriod


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "price_monthly_usd", "price_annual_usd",
                    "monthly_summary_quota", "monthly_chat_quota", "is_active")
    ordering = ("sort_order",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "billing_cycle", "current_period_end", "cancel_at_period_end")
    list_filter = ("status", "plan")
    search_fields = ("user__email", "paddle_subscription_id")


@admin.register(UsagePeriod)
class UsagePeriodAdmin(admin.ModelAdmin):
    list_display = ("user", "period", "summaries_used", "chats_used", "tokens_used")
    list_filter = ("period",)
    search_fields = ("user__email",)
