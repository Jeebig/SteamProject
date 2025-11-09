from django.db import migrations, models


class Migration(migrations.Migration):
    # Keep this earlier migration as depending on 0011, but since avatar added later in 0034 we convert to no-op.
    dependencies = [
        ('store', '0011_alter_game_sysreq_min_alter_game_sysreq_rec'),
    ]
    operations = []
