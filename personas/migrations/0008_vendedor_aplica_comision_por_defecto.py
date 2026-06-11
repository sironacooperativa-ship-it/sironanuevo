from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personas", "0007_vendedor_grupo"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendedor",
            name="aplica_comision_por_defecto",
            field=models.BooleanField(
                default=True,
                help_text="Si está activo, al armar presupuestos o ventas con este vendedor la opción «Aplicar comisión» viene marcada.",
                verbose_name="Aplicar comisión por defecto",
            ),
        ),
    ]
