from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0011_alter_game_sysreq_min_alter_game_sysreq_rec'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='is_top_seller',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='game',
            name='is_new_release',
            field=models.BooleanField(default=False),
        ),
    ]
