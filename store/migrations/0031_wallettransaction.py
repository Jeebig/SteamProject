from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal

class Migration(migrations.Migration):

    dependencies = [
        ('store', '0030_userprofile_balance'),
    ]

    operations = [
        migrations.CreateModel(
            name='WalletTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(help_text='Валюта amount (preferred_currency пользователя).', max_length=5, choices=[('USD','USD'),('EUR','EUR'),('UAH','UAH'),('GBP','GBP'),('RUB','RUB'),('JPY','JPY'),('CAD','CAD'),('AUD','AUD'),('CNY','CNY'),('PLN','PLN')])),
                ('source_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, help_text='Исходная введённая сумма (если отличалась)')),
                ('source_currency', models.CharField(blank=True, choices=[('USD','USD'),('EUR','EUR'),('UAH','UAH'),('GBP','GBP'),('RUB','RUB'),('JPY','JPY'),('CAD','CAD'),('AUD','AUD'),('CNY','CNY'),('PLN','PLN')], max_length=5, null=True)),
                ('kind', models.CharField(choices=[('topup','Пополнение'),('purchase_deduct','Покупка'),('manual_adjust','Корректировка'),('refund','Возврат')], max_length=20)),
                ('balance_after', models.DecimalField(decimal_places=2, max_digits=12)),
                ('description', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wallet_transactions', to='auth.user')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='wallettransaction',
            index=models.Index(fields=['user', 'created_at'], name='store_walle_user_id_4c4d13_idx'),
        ),
        migrations.AddIndex(
            model_name='wallettransaction',
            index=models.Index(fields=['user', 'kind'], name='store_walle_user_id_70887a_idx'),
        ),
    ]
