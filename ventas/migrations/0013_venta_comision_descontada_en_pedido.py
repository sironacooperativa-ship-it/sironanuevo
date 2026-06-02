from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ventas", "0012_backfill_snapshot_ventas_pagadas"),
    ]

    operations = [
        migrations.AddField(
            model_name="venta",
            name="comision_descontada_en_pedido",
            field=models.BooleanField(
                default=False,
                help_text="Si aplica comisión y está activo, el cobro en caja es neto menos comisión.",
            ),
        ),
    ]
