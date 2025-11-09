from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0007_platform_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='sysreq_min',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='game',
            name='sysreq_rec',
            field=models.TextField(blank=True, default=''),
        ),
    ]
