from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("productos", "0004_producto_fecha_vencimiento"),
    ]

    operations = [
        migrations.AlterField(
            model_name="producto",
            name="en_lista_precios",
            field=models.BooleanField(default=True),
        ),
    ]
