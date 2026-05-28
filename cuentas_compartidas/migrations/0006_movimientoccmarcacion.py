from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cuentas_compartidas", "0005_operacioncompartida_creado_por"),
    ]

    operations = [
        migrations.CreateModel(
            name="MovimientoCCMarcacion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "mov_tipo",
                    models.CharField(
                        choices=[("operacion", "Operación"), ("cancelacion", "Cancelación")],
                        max_length=12,
                    ),
                ),
                ("objeto_id", models.PositiveIntegerField()),
                ("marcado", models.BooleanField(db_index=True, default=True)),
                ("marcado_en", models.DateTimeField(auto_now=True)),
                (
                    "marcado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cc_marcaciones",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Marcación cuenta corriente",
                "verbose_name_plural": "Marcaciones cuenta corriente",
            },
        ),
        migrations.AddConstraint(
            model_name="movimientoccmarcacion",
            constraint=models.UniqueConstraint(
                fields=("mov_tipo", "objeto_id"),
                name="uniq_cc_marcacion_mov",
            ),
        ),
    ]
