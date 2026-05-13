from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("productos", "0009_alter_producto_en_lista_precios_default_false"),
    ]

    operations = [
        migrations.AddField(
            model_name="producto",
            name="deshabilitado_por_stock",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="producto",
            name="listas_stock_snapshot",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
