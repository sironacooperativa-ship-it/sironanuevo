from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("productos", "0008_lista_precio_item"),
    ]

    operations = [
        migrations.AlterField(
            model_name="producto",
            name="en_lista_precios",
            field=models.BooleanField(default=False),
        ),
    ]
