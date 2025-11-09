from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0011_alter_game_sysreq_min_alter_game_sysreq_rec'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='last_username_change',
            field=models.DateTimeField(blank=True, null=True, help_text='Timestamp последней успешной смены имени пользователя'),
        ),
    ]
