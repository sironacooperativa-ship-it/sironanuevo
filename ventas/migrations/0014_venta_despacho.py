from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ventas", "0013_venta_comision_descontada_en_pedido"),
    ]

    operations = [
        migrations.AddField(
            model_name="venta",
            name="despacho_armado",
            field=models.BooleanField(
                default=False,
                help_text="Pedido preparado / armado para entrega.",
            ),
        ),
        migrations.AddField(
            model_name="venta",
            name="despacho_despachado",
            field=models.BooleanField(
                default=False,
                help_text="Pedido entregado o despachado al cliente.",
            ),
        ),
    ]
