from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0011_alter_game_sysreq_min_alter_game_sysreq_rec'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='expires_at',
            field=models.DateTimeField(blank=True, help_text='Когда уведомление можно авто-удалить', null=True),
        ),
        migrations.CreateModel(
            name='CurrencyRate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('base', models.CharField(max_length=5)),
                ('target', models.CharField(max_length=5)),
                ('rate', models.DecimalField(decimal_places=8, max_digits=18)),
                ('fetched_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'indexes': [
                    models.Index(fields=['base', 'target'], name='store_curre_base_ta_0a7b63_idx'),
                    models.Index(fields=['fetched_at'], name='store_curre_fetched_4f8b0a_idx'),
                ],
                'unique_together': {('base', 'target', 'fetched_at')},
            },
        ),
    ]
