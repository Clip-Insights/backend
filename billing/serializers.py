from rest_framework import serializers


class CheckoutInputSerializer(serializers.Serializer):
    plan_code = serializers.SlugField()  # plans.Plan.slug
    billing_cycle = serializers.ChoiceField(choices=["monthly", "annual"], default="monthly")
