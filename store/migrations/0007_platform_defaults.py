from typing import Any

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def set_default_platforms(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Game: Any = apps.get_model('store', 'Game')
    # Assume Windows support by default if no platform flags were set previously
    Game.objects.filter(
        supports_windows=False,
        supports_mac=False,
        supports_linux=False,
    ).update(supports_windows=True)


def unset_default_platforms(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    # No-op reverse migration: we don't know original values safely
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0006_add_platform_flags'),
    ]

    operations = [
        migrations.RunPython(set_default_platforms, unset_default_platforms),
    ]
