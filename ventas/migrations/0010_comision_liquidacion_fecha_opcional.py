from datetime import date

from django.db import migrations, models


def forwards_fecha_liq(apps, schema_editor):
    Liq = apps.get_model("ventas", "ComisionLiquidacionPago")
    for row in Liq.objects.all():
        if row.anio and row.mes:
            row.fecha_liquidacion = date(int(row.anio), int(row.mes), 1)
        else:
            row.fecha_liquidacion = row.creado_en.date() if row.creado_en else date.today()
        row.save(update_fields=["fecha_liquidacion"])


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0009_comision_liquidacion_pago"),
    ]

    operations = [
        migrations.AddField(
            model_name="comisionliquidacionpago",
            name="fecha_liquidacion",
            field=models.DateField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name="comisionliquidacionpago",
            name="anio",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name="comisionliquidacionpago",
            name="mes",
            field=models.PositiveSmallIntegerField(null=True, blank=True),
        ),
        migrations.RunPython(forwards_fecha_liq, migrations.RunPython.noop),
    ]
