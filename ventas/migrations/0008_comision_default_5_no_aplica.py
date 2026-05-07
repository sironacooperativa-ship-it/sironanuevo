from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ventas", "0007_venta_envio"),
    ]

    operations = [
        migrations.AlterField(
            model_name="venta",
            name="aplica_comision",
            field=models.BooleanField(
                default=False,
                help_text="Si aplica, la comisión se descuenta del ingreso en caja al cobrar.",
            ),
        ),
        migrations.AlterField(
            model_name="venta",
            name="comision_porcentaje",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("5.00"),
                max_digits=6,
            ),
        ),
    ]
