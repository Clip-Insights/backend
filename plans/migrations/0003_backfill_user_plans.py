"""Give every existing user an explicit free UserPlan row.

Accounts created before the plans app existed have no UserPlan; runtime code
treats "no row" as free, but an explicit row keeps the data model uniform for
new-user signals, admin views and the Paddle upsert contract. Idempotent:
only users without a row are touched.
"""
from django.db import migrations


def backfill_user_plans(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")
    UserPlan = apps.get_model("plans", "UserPlan")
    User = apps.get_model("account", "User")

    free = Plan.objects.get(slug="free")
    missing = User.objects.filter(user_plan__isnull=True)
    UserPlan.objects.bulk_create(
        [UserPlan(user=user, plan=free) for user in missing.iterator()],
        ignore_conflicts=True,
    )


def remove_backfilled_rows(apps, schema_editor):
    # Reversing simply drops the free rows; paid rows are preserved.
    Plan = apps.get_model("plans", "Plan")
    UserPlan = apps.get_model("plans", "UserPlan")
    UserPlan.objects.filter(plan=Plan.objects.get(slug="free")).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0002_seed_plans"),
        ("account", "0002_builtin_roles"),
    ]

    operations = [
        migrations.RunPython(backfill_user_plans, remove_backfilled_rows),
    ]
