from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("productos", "0002_producto_stock"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MovimientoStock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tipo", models.CharField(choices=[("IN", "Entrada"), ("OUT", "Salida")], max_length=3)),
                ("cantidad", models.IntegerField()),
                ("numero_boleta", models.CharField(blank=True, default="", max_length=50)),
                ("proveedor", models.CharField(blank=True, default="", max_length=255)),
                ("numero_factura", models.CharField(blank=True, default="", max_length=50)),
                ("destinatario", models.CharField(blank=True, default="", max_length=255)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("producto", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="movimientos_stock", to="productos.producto")),
                ("usuario", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-creado_en", "-id"]},
        ),
    ]

