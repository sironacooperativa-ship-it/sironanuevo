from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("productos", "0002_producto_stock"),
    ]

    operations = [
        migrations.CreateModel(
            name="ListaPrecios",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nombre", models.CharField(max_length=100)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-creado_en", "-id"],
                "unique_together": {("nombre",)},
            },
        ),
        migrations.AddField(
            model_name="listaprecios",
            name="productos",
            field=models.ManyToManyField(related_name="listas_precios", to="productos.producto"),
        ),
    ]

