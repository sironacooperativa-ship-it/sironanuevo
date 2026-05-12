from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("compras", "0004_compra_anulada_movimiento_credito"),
    ]

    operations = [
        migrations.AddField(
            model_name="compra",
            name="modo",
            field=models.CharField(
                choices=[("PRO", "Productos (detalle)"), ("FAC", "Factura sin detalle")],
                db_index=True,
                default="PRO",
                max_length=3,
            ),
        ),
        migrations.AlterField(
            model_name="compra",
            name="producto",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="compras_origen",
                to="productos.producto",
            ),
        ),
    ]
