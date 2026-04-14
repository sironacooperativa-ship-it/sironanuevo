from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("productos", "0003_listaprecios"),
    ]

    operations = [
        migrations.AddField(
            model_name="producto",
            name="fecha_vencimiento",
            field=models.DateField(blank=True, null=True),
        ),
    ]

