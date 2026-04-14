from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("personas", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MovimientoCaja",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha", models.DateField()),
                ("operacion", models.CharField(max_length=255)),
                ("tipo", models.CharField(choices=[("IN", "Ingreso"), ("OUT", "Egreso")], max_length=3)),
                ("monto", models.DecimalField(decimal_places=2, max_digits=14)),
                ("medio_pago", models.CharField(choices=[("CASH", "Efectivo"), ("TRF", "Transferencia"), ("MP", "MercadoPago"), ("CHQ", "Cheque"), ("OTH", "Otro")], default="CASH", max_length=10)),
                ("banco", models.CharField(blank=True, default="", max_length=100)),
                ("numero_cheque", models.CharField(blank=True, default="", max_length=50)),
                ("fecha_vencimiento_cheque", models.DateField(blank=True, null=True)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("vendedor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="personas.vendedor")),
            ],
            options={"ordering": ["fecha", "id"]},
        ),
    ]

