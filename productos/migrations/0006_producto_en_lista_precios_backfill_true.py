from django.db import migrations


def forwards(apps, schema_editor):
    Producto = apps.get_model("productos", "Producto")
    Producto.objects.filter(en_lista_precios=False).update(en_lista_precios=True)


def backwards(apps, schema_editor):
    # No revertimos: no sabemos cuáles estaban en False intencionalmente.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("productos", "0005_alter_producto_en_lista_precios_default"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

