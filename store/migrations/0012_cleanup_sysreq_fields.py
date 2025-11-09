from django.db import migrations, models


class Migration(migrations.Migration):
    """Consolidate duplicate sysreq_min/sysreq_rec field definitions.

    Prior migrations added the fields twice with and without help_text. The final
    model keeps a single definition including help_text and default ''. This
    migration ensures defaults/help_text are consistent without creating new columns.
    """

    dependencies = [
        ('store', '0011_alter_game_sysreq_min_alter_game_sysreq_rec'),
    ]

    operations = [
        migrations.AlterField(
            model_name='game',
            name='sysreq_min',
            field=models.TextField(blank=True, default='', help_text='Минимальные системные требования (можно HTML)'),
        ),
        migrations.AlterField(
            model_name='game',
            name='sysreq_rec',
            field=models.TextField(blank=True, default='', help_text='Рекомендуемые системные требования (можно HTML)'),
        ),
    ]
