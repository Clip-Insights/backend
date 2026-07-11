"""Merge the builtin-roles rework (0002) with main's schema-drift fix (0003).

0003 re-adds is_admin / allocated_space when it runs after 0002 has dropped
them (its ADD COLUMN IF NOT EXISTS was written for a drifted production DB).
The model has neither field, so drop them here to converge every DB state.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0002_builtin_roles"),
        ("account", "0003_fix_account_user_schema"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE account_user DROP COLUMN IF EXISTS is_admin;",
                "ALTER TABLE account_user DROP COLUMN IF EXISTS allocated_space;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
