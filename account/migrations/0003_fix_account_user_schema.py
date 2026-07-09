# Schema drift: 0001_initial was recorded as applied without is_admin / allocated_space.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE account_user ADD COLUMN IF NOT EXISTS is_admin BOOL NOT NULL DEFAULT false;",
                "ALTER TABLE account_user ADD COLUMN IF NOT EXISTS allocated_space FLOAT8 NOT NULL DEFAULT 52428800;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
