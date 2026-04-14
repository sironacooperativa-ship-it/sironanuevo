from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Producto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(db_index=True, max_length=6, unique=True)),
                ("descripcion", models.CharField(max_length=255)),
                ("tipo", models.CharField(choices=[("MED", "Medicamentos"), ("AC", "Accesorios"), ("OT", "Otros")], max_length=3)),
                ("costo", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("porcentaje_ganancia", models.DecimalField(decimal_places=2, default=Decimal("30.00"), max_digits=6)),
                ("precio_venta", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("precio_venta_editado", models.BooleanField(default=False)),
                ("habilitado", models.BooleanField(default=True)),
                ("en_lista_precios", models.BooleanField(default=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-actualizado_en", "-id"]},
        )
    ]

