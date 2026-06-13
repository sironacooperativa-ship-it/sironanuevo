from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("productos", "0011_producto_laboratorio"),
        ("ventas", "0015_punto_stock_armado"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArmadoColectivoGuardado",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=500)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                (
                    "creado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="armados_colectivos_guardados",
                        to="auth.user",
                    ),
                ),
            ],
            options={
                "ordering": ["-creado_en", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ArmadoColectivoLineaGuardada",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(max_length=32)),
                ("descripcion", models.CharField(max_length=255)),
                ("cantidad_total", models.PositiveIntegerField()),
                ("costo_unitario", models.DecimalField(decimal_places=2, max_digits=12)),
                ("precio_venta", models.DecimalField(decimal_places=2, max_digits=12)),
                ("orden", models.PositiveIntegerField(default=0)),
                (
                    "armado",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lineas",
                        to="ventas.armadocolectivoguardado",
                    ),
                ),
                (
                    "producto",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lineas_armado_colectivo",
                        to="productos.producto",
                    ),
                ),
            ],
            options={
                "ordering": ["orden", "id"],
            },
        ),
        migrations.AddField(
            model_name="armadocolectivoguardado",
            name="ventas",
            field=models.ManyToManyField(related_name="armados_colectivos_guardados", to="ventas.venta"),
        ),
        migrations.CreateModel(
            name="ArmadoColectivoAsignacion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cantidad", models.PositiveIntegerField()),
                (
                    "linea",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="asignaciones",
                        to="ventas.armadocolectivolineaguardada",
                    ),
                ),
                (
                    "punto",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="asignaciones_armado",
                        to="ventas.puntostockarmado",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("linea", "punto"),
                        name="ventas_armado_asignacion_linea_punto_unique",
                    )
                ],
            },
        ),
    ]
