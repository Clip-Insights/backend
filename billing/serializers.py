from rest_framework import serializers

from billing.models import Plan


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "code", "name", "price_monthly_usd", "price_annual_usd",
            "monthly_summary_quota", "monthly_chat_quota", "monthly_token_quota",
            "features", "paddle_price_id_monthly", "paddle_price_id_annual",
        ]


class CheckoutInputSerializer(serializers.Serializer):
    plan_code = serializers.CharField()
    billing_cycle = serializers.ChoiceField(choices=["monthly", "annual"], default="monthly")
