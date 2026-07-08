"""Move to Django's built-in role flags.

The old custom `is_admin` flag is replaced by the standard `is_staff` +
`is_superuser` pair (existing admins become superusers). `allocated_space` is
dropped: storage caps now come from the user's plan (see the `plans` app).
"""
from django.db import migrations, models


def promote_admins(apps, schema_editor):
    User = apps.get_model("account", "User")
    User.objects.filter(is_admin=True).update(is_staff=True, is_superuser=True)


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_staff",
            field=models.BooleanField(
                default=False,
                help_text="Designates whether the user can log into this admin site.",
                verbose_name="staff status",
            ),
        ),
        migrations.RunPython(promote_admins, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="user",
            name="is_admin",
        ),
        migrations.RemoveField(
            model_name="user",
            name="allocated_space",
        ),
    ]
