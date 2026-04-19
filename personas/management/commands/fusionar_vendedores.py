from __future__ import annotations

import unicodedata
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from caja.models import MovimientoCaja
from personas.models import Comprador, Vendedor
from presupuestos.models import Presupuesto
from ventas.models import Venta


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = " ".join(s.split())
    return s


class Command(BaseCommand):
    help = "Fusiona vendedores duplicados por (apellido+nombre) normalizados."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Aplica cambios (si no, solo muestra qué haría).",
        )
        parser.add_argument(
            "--only-unlinked",
            action="store_true",
            help="Solo fusiona duplicados sin usuario vinculado (usuario_id IS NULL).",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        only_unlinked = bool(options["only_unlinked"])

        qs = Vendedor.objects.all().order_by("apellido", "nombre", "pk")
        grupos: dict[tuple[str, str], list[Vendedor]] = defaultdict(list)
        for v in qs:
            key = (_norm(v.apellido), _norm(v.nombre))
            if not key[0] and not key[1]:
                continue
            grupos[key].append(v)

        candidatos = [(k, vs) for k, vs in grupos.items() if len(vs) > 1]
        if not candidatos:
            self.stdout.write("No hay vendedores duplicados por nombre/apellido.")
            return

        def pick_primary(vs: list[Vendedor]) -> Vendedor:
            with_user = [v for v in vs if v.usuario_id]
            if with_user:
                return sorted(with_user, key=lambda x: (x.pk,))[0]
            return sorted(vs, key=lambda x: (x.pk,))[0]

        merges = 0
        skips = 0
        for (ap, nom), vs in candidatos:
            if only_unlinked and any(v.usuario_id for v in vs):
                continue

            usuario_ids = sorted({v.usuario_id for v in vs if v.usuario_id})
            if len(usuario_ids) > 1:
                skips += 1
                self.stdout.write(
                    f"SKIP {ap!r}, {nom!r}: hay {len(usuario_ids)} usuarios distintos vinculados."
                )
                continue

            primary = pick_primary(vs)
            dups = [v for v in vs if v.pk != primary.pk]
            dup_ids = [v.pk for v in dups]
            if not dup_ids:
                continue

            self.stdout.write(
                f"{'APLICA' if apply else 'DRY'} merge {ap!r}, {nom!r}: "
                f"keep {primary.codigo}(id={primary.pk}) ← {', '.join(str(i) for i in dup_ids)}"
            )

            if not apply:
                merges += 1
                continue

            with transaction.atomic():
                primary_lock = Vendedor.objects.select_for_update().get(pk=primary.pk)
                dup_locks = list(Vendedor.objects.select_for_update().filter(pk__in=dup_ids))

                # Reasignar referencias
                Comprador.objects.filter(vendedor_asignado_id__in=dup_ids).update(
                    vendedor_asignado_id=primary_lock.pk
                )
                Venta.objects.filter(vendedor_id__in=dup_ids).update(vendedor_id=primary_lock.pk)
                Presupuesto.objects.filter(vendedor_id__in=dup_ids).update(vendedor_id=primary_lock.pk)
                MovimientoCaja.objects.filter(vendedor_id__in=dup_ids).update(vendedor_id=primary_lock.pk)

                # Vincular usuario (si había uno en el grupo)
                if not primary_lock.usuario_id and usuario_ids:
                    primary_lock.usuario_id = usuario_ids[0]
                    primary_lock.save(update_fields=["usuario"])

                # Desvincular y borrar duplicados
                for dv in dup_locks:
                    if dv.usuario_id:
                        dv.usuario_id = None
                        dv.save(update_fields=["usuario"])
                Vendedor.objects.filter(pk__in=dup_ids).delete()

            merges += 1

        self.stdout.write(f"Listo. merges={merges} skips={skips} apply={apply}.")

