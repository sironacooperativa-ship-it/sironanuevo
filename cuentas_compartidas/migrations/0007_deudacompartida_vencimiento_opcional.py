from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cuentas_compartidas", "0006_movimientoccmarcacion"),
    ]

    operations = [
        migrations.AlterField(
            model_name="deudacompartida",
            name="vencimiento",
            field=models.DateField(blank=True, null=True),
        ),
    ]
