from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('store', '0033_rename_store_curre_base_ta_0a7b63_idx_store_curre_base_d1ab9b_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='avatar',
            field=models.ImageField(upload_to='profiles/avatars/', null=True, blank=True),
        ),
    ]
