from django.contrib import admin

from .models import Plan, UsageEvent, UserPlan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "slug",
        "name",
        "monthly_price_usd",
        "is_active",
        "daily_summaries",
        "daily_chat_messages",
        "daily_transcriptions",
        "storage_limit_mb",
    )
    list_filter = ("is_active",)
    ordering = ("sort_order",)


@admin.register(UserPlan)
class UserPlanAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "expires_at", "updated_at")
    list_filter = ("plan",)
    search_fields = ("user__email",)
    autocomplete_fields = ("user",)


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "created_at")
    list_filter = ("kind",)
    search_fields = ("user__email",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
