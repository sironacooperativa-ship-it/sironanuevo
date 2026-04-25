from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from productos.models import ListaPrecioItem, ListaPrecios, Producto


class Command(BaseCommand):
    help = (
        "Crea items faltantes en listas de precio (NO Farmacia) "
        "copiando el precio actual del producto."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--solo-habilitados",
            action="store_true",
            help="Solo considera productos habilitados.",
        )
        parser.add_argument(
            "--solo-si-ya-tiene-alguna-lista",
            action="store_true",
            help="Solo completa productos que ya estén en al menos una lista de rubro.",
        )

    def handle(self, *args, **options):
        solo_hab = bool(options.get("solo_habilitados"))
        solo_si_tiene = bool(options.get("solo_si_ya_tiene_alguna_lista"))

        listas = list(ListaPrecios.objects.filter(es_farmacia=False).order_by("id"))
        if not listas:
            self.stdout.write("No hay listas de rubro (no Farmacia).")
            return

        productos = Producto.objects.all()
        if solo_hab:
            productos = productos.filter(habilitado=True)

        creados = 0
        existentes = 0
        saltados = 0

        with transaction.atomic():
            for p in productos.iterator(chunk_size=500):
                if solo_si_tiene and not ListaPrecioItem.objects.filter(producto_id=p.pk).exists():
                    saltados += 1
                    continue
                for lista in listas:
                    obj, was_created = ListaPrecioItem.objects.get_or_create(
                        lista_id=lista.pk,
                        producto_id=p.pk,
                        defaults={"precio_venta": p.precio_venta},
                    )
                    if was_created:
                        creados += 1
                    else:
                        existentes += 1

        self.stdout.write(
            f"Listo. Items creados: {creados}. Ya existentes: {existentes}. Productos saltados: {saltados}."
        )

