from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("presupuestos", "0004_fecha_pago_opcional"),
    ]

    operations = [
        migrations.AddField(
            model_name="presupuesto",
            name="aplica_comision",
            field=models.BooleanField(
                default=True,
                help_text="Si aplica, al generar el pedido la comisión se discrimina y descuenta del ingreso en caja.",
            ),
        ),
    ]
