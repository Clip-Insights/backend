from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Plan
from .serializers import PlanSerializer
from .services import get_plan_for, usage_summary


class PlanListView(APIView):
    """Public plan catalogue: powers the pricing page and guest limit values."""

    permission_classes = [AllowAny]

    def get(self, request):
        plans = Plan.objects.filter(is_active=True)
        return Response({"plans": PlanSerializer(plans, many=True).data}, status=status.HTTP_200_OK)


class MyPlanView(APIView):
    """The caller's effective plan plus live usage counters."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        plan = get_plan_for(request.user)
        return Response(
            {"plan": PlanSerializer(plan).data, "usage": usage_summary(request.user, plan)},
            status=status.HTTP_200_OK,
        )
