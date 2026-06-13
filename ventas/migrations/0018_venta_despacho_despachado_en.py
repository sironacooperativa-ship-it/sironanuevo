from django.db import migrations, models
from django.utils import timezone


def backfill_despacho_despachado_en(apps, schema_editor):
    Venta = apps.get_model("ventas", "Venta")
    for venta in Venta.objects.filter(despacho_despachado=True, despacho_despachado_en__isnull=True):
        ts = venta.actualizado_en or venta.creado_en
        if ts is None:
            ts = timezone.now()
        Venta.objects.filter(pk=venta.pk).update(despacho_despachado_en=ts)


class Migration(migrations.Migration):

    dependencies = [
        ("ventas", "0017_armado_colectivo_revision"),
    ]

    operations = [
        migrations.AddField(
            model_name="venta",
            name="despacho_despachado_en",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Momento en que se marcó como despachado (para archivar al historial).",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_despacho_despachado_en, migrations.RunPython.noop),
    ]
