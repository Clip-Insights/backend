from django.urls import path

from .views import MyPlanView, PlanListView

urlpatterns = [
    path("", PlanListView.as_view(), name="plan-list"),
    path("me/", MyPlanView.as_view(), name="my-plan"),
]
