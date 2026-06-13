from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ventas", "0016_armado_colectivo_guardado"),
    ]

    operations = [
        migrations.AddField(
            model_name="armadocolectivoguardado",
            name="nota_revision",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="armadocolectivoguardado",
            name="requiere_revision",
            field=models.BooleanField(
                default=False,
                help_text="True si cambió la composición del armado (p. ej. se eliminó un pedido del historial).",
            ),
        ),
    ]
