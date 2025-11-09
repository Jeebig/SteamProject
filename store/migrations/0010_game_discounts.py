from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0009_merge_sysreq'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='discount_percent',
            field=models.PositiveSmallIntegerField(default=0, help_text='Скидка в процентах, 0 если нет'),
        ),
        migrations.AddField(
            model_name='game',
            name='original_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
    ]
