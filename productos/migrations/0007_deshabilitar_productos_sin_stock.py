from django.db import migrations


def forwards(apps, schema_editor):
    Producto = apps.get_model("productos", "Producto")
    Producto.objects.filter(stock=0).update(habilitado=False, en_lista_precios=False)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("productos", "0006_producto_en_lista_precios_backfill_true"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
