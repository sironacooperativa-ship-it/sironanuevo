from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("administrador", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="registroactividad",
            name="descripcion",
            field=models.TextField(blank=True, default=""),
        ),
    ]
