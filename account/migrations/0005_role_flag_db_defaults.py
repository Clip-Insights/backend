"""Add DB-level defaults to the role flag columns.

Django drops the database default after backfilling an AddField, leaving
`is_staff` / `is_superuser` as NOT NULL with no DB default. Any INSERT that
omits them (e.g. a stale application image whose model predates the flag)
then fails with a NotNullViolation. Restoring a DB default makes user
creation resilient to code/DB version skew during rolling deploys.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0004_merge_roles_and_schema_fix"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE account_user ALTER COLUMN is_staff SET DEFAULT false;",
                "ALTER TABLE account_user ALTER COLUMN is_superuser SET DEFAULT false;",
            ],
            reverse_sql=[
                "ALTER TABLE account_user ALTER COLUMN is_staff DROP DEFAULT;",
                "ALTER TABLE account_user ALTER COLUMN is_superuser DROP DEFAULT;",
            ],
        ),
    ]
