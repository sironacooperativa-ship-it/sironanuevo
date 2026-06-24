from django.db import migrations, models
import django.db.models.deletion


def archivar_pedidos_despachados(apps, schema_editor):
    Venta = apps.get_model("ventas", "Venta")
    VentaLinea = apps.get_model("ventas", "VentaLinea")
    Producto = apps.get_model("productos", "Producto")

    venta_ids = list(
        Venta.objects.filter(despacho_despachado=True).values_list("pk", flat=True)
    )
    for vid in venta_ids:
        for ln in VentaLinea.objects.filter(venta_id=vid).iterator():
            updates = {}
            try:
                prod = Producto.objects.filter(pk=ln.producto_id).first() if ln.producto_id else None
            except Exception:
                prod = None
            if prod:
                if not (ln.codigo_snapshot or "").strip():
                    updates["codigo_snapshot"] = (prod.codigo or "")[:6]
                if not (ln.descripcion_snapshot or "").strip():
                    updates["descripcion_snapshot"] = (prod.descripcion or "")[:255]
                if not (getattr(ln, "marca_snapshot", None) or "").strip():
                    updates["marca_snapshot"] = (getattr(prod, "laboratorio", None) or "")[:120]
                updates["producto_id"] = None
            if updates:
                VentaLinea.objects.filter(pk=ln.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("ventas", "0018_venta_despacho_despachado_en"),
    ]

    operations = [
        migrations.AddField(
            model_name="ventalinea",
            name="marca_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Laboratorio/marca congelado al archivar el pedido despachado.",
                max_length=120,
            ),
        ),
        migrations.AlterField(
            model_name="ventalinea",
            name="producto",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="lineas_venta",
                to="productos.producto",
            ),
        ),
        migrations.RunPython(archivar_pedidos_despachados, migrations.RunPython.noop),
    ]
