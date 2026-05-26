from django.db import migrations


def crear_negocios_iniciales(apps, schema_editor):
    Negocio = apps.get_model("cuentas_compartidas", "Negocio")
    for nombre in ("Negocio 1", "Negocio 2", "Negocio 3", "Negocio 4"):
        Negocio.objects.get_or_create(nombre=nombre, defaults={"activo": True})


def revertir_negocios_iniciales(apps, schema_editor):
    Negocio = apps.get_model("cuentas_compartidas", "Negocio")
    Negocio.objects.filter(nombre__in=("Negocio 1", "Negocio 2", "Negocio 3", "Negocio 4")).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cuentas_compartidas", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(crear_negocios_iniciales, revertir_negocios_iniciales),
    ]
