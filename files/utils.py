from django.db.models import Sum

from plans.services import get_plan_for

from .models import File


def storage_info(user):
    """Used/remaining/allowed storage in bytes, with the cap taken from the user's plan."""
    used_space = File.objects.filter(user_id=user.id).aggregate(total=Sum("size"))["total"] or 0
    allowed_space = get_plan_for(user).storage_limit_bytes
    return {
        "used_space": used_space,
        "allowed_space": allowed_space,
        "remaining_space": max(0, allowed_space - used_space),
    }
