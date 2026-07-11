"""Keep every user with an explicit UserPlan row from the moment they sign up.

Legacy users (created before the plans app existed) are covered twice over:
the 0003 data migration backfills them in bulk, and `services.get_plan_for`
lazily self-heals any row that is still missing on their first authenticated
request. New users get their row here, whatever path created them (email
signup, Google OAuth, createsuperuser, admin).
"""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="plans.create_default_user_plan")
def create_default_user_plan(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    from .models import Plan, UserPlan

    UserPlan.objects.get_or_create(
        user=instance, defaults={"plan": Plan.objects.get(slug=Plan.FREE)}
    )
