from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ventas", "0004_fecha_pago_opcional"),
    ]

    operations = [
        migrations.AddField(
            model_name="venta",
            name="aplica_comision",
            field=models.BooleanField(
                default=True,
                help_text="Si aplica, la comisión se descuenta del ingreso en caja al cobrar.",
            ),
        ),
    ]
