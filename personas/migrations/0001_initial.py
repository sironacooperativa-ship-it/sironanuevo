from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Comprador",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(db_index=True, max_length=6, unique=True)),
                ("nombre", models.CharField(max_length=100)),
                ("apellido", models.CharField(max_length=100)),
                ("dni", models.CharField(blank=True, default="", max_length=20)),
                ("telefono", models.CharField(blank=True, default="", max_length=50)),
                ("mail", models.EmailField(blank=True, default="", max_length=254)),
                ("direccion", models.CharField(blank=True, default="", max_length=255)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Comprador", "verbose_name_plural": "Compradores", "ordering": ["apellido", "nombre", "codigo"]},
        ),
        migrations.CreateModel(
            name="Proveedor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(db_index=True, max_length=6, unique=True)),
                ("nombre", models.CharField(max_length=100)),
                ("apellido", models.CharField(max_length=100)),
                ("dni", models.CharField(blank=True, default="", max_length=20)),
                ("telefono", models.CharField(blank=True, default="", max_length=50)),
                ("mail", models.EmailField(blank=True, default="", max_length=254)),
                ("direccion", models.CharField(blank=True, default="", max_length=255)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Proveedor", "verbose_name_plural": "Proveedores", "ordering": ["apellido", "nombre", "codigo"]},
        ),
        migrations.CreateModel(
            name="Vendedor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(db_index=True, max_length=6, unique=True)),
                ("nombre", models.CharField(max_length=100)),
                ("apellido", models.CharField(max_length=100)),
                ("dni", models.CharField(blank=True, default="", max_length=20)),
                ("telefono", models.CharField(blank=True, default="", max_length=50)),
                ("mail", models.EmailField(blank=True, default="", max_length=254)),
                ("direccion", models.CharField(blank=True, default="", max_length=255)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("comision_porcentaje", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=6)),
            ],
            options={"verbose_name": "Vendedor", "verbose_name_plural": "Vendedores", "ordering": ["apellido", "nombre", "codigo"]},
        ),
    ]

