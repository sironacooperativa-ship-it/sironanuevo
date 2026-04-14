from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("compras", "0002_compra_actualizado_en_compra_actualizado_por_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="compra",
            name="fecha_vencimiento_pedido",
            field=models.DateField(blank=True, null=True),
        ),
    ]
