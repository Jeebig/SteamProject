from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('store', '0034_userprofile_avatar'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='bio',
            field=models.TextField(blank=True, help_text="Краткое описание / 'О себе'"),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='theme_color',
            field=models.CharField(max_length=20, blank=True, help_text="Цвет акцента профиля (#1b6b80 по умолчанию если пусто)"),
        ),
    ]