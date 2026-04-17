# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("compras", "0003_compra_fecha_vencimiento_pedido_opcional"),
    ]

    operations = [
        migrations.AddField(
            model_name="compra",
            name="anulada",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="compra",
            name="movimiento_credito",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="compra_nota_credito",
                to="caja.movimientocaja",
            ),
        ),
    ]
