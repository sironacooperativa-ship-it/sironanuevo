from django.db import migrations, models


DEFAULT_PUNTOS = ("Sirona", "Male", "Guada", "Padua")


def seed_puntos_stock(apps, schema_editor):
    PuntoStockArmado = apps.get_model("ventas", "PuntoStockArmado")
    for i, nombre in enumerate(DEFAULT_PUNTOS):
        PuntoStockArmado.objects.get_or_create(nombre=nombre, defaults={"orden": i})


class Migration(migrations.Migration):

    dependencies = [
        ("ventas", "0014_venta_despacho"),
    ]

    operations = [
        migrations.CreateModel(
            name="PuntoStockArmado",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=80, unique=True)),
                ("orden", models.PositiveIntegerField(default=0)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Punto de stock (armado)",
                "verbose_name_plural": "Puntos de stock (armado)",
                "ordering": ["orden", "nombre", "id"],
            },
        ),
        migrations.RunPython(seed_puntos_stock, migrations.RunPython.noop),
    ]
