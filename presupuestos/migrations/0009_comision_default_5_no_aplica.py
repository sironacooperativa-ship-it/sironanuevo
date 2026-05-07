from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("presupuestos", "0008_presupuesto_envio"),
    ]

    operations = [
        migrations.AlterField(
            model_name="presupuesto",
            name="aplica_comision",
            field=models.BooleanField(
                default=False,
                help_text="Si aplica, al generar el pedido la comisión se discrimina y descuenta del ingreso en caja.",
            ),
        ),
        migrations.AlterField(
            model_name="presupuesto",
            name="comision_porcentaje",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("5.00"),
                max_digits=6,
            ),
        ),
    ]
