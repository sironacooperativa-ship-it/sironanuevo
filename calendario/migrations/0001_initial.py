from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Evento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha", models.DateField()),
                ("titulo", models.CharField(max_length=255)),
                ("tipo", models.CharField(choices=[("MAN", "Manual"), ("PED", "Pedido")], default="MAN", max_length=3)),
                ("descripcion", models.TextField(blank=True, default="")),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["fecha", "id"]},
        ),
    ]

