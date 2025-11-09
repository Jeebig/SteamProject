from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('store', '0031_wallettransaction'),
    ]

    operations = [
        migrations.CreateModel(
            name='PriceSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price', models.DecimalField(max_digits=10, decimal_places=2)),
                ('currency', models.CharField(max_length=5, choices=[('USD','USD'),('EUR','EUR'),('UAH','UAH'),('GBP','GBP'),('RUB','RUB'),('JPY','JPY'),('CAD','CAD'),('AUD','AUD'),('CNY','CNY'),('PLN','PLN')], default='USD')),
                ('snapshot_date', models.DateField()),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_snapshots', to='store.game')),
            ],
            options={
                'indexes': [models.Index(fields=['game','snapshot_date'], name='store_price_game_id_snapsho_idx')],
                'unique_together': {('game','snapshot_date')},
            },
        ),
        migrations.AddField(
            model_name='userprofile',
            name='notify_price_drop',
            field=models.BooleanField(default=True, help_text='Уведомлять о снижении цены игр из списка желаемого'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='email_price_drop',
            field=models.BooleanField(default=False, help_text='Присылать email о снижении цены (если указан email)'),
        ),
    ]
