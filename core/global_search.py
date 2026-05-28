"""Búsqueda global del topbar (JSON)."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse

from cuentas_compartidas.auth import puede_usar_cuentas_compartidas
from cuentas_compartidas.models import CancelacionDeuda, OperacionCompartida
from personas.models import Comprador, Vendedor
from presupuestos.models import Presupuesto
from productos.models import Producto

MAX_PER_GROUP = 6
MIN_QUERY_LEN = 2


def _parse_monto(text: str) -> Decimal | None:
    raw = (text or "").strip().replace("$", "").replace(" ", "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        v = Decimal(raw)
        return v if v >= 0 else None
    except InvalidOperation:
        return None


def _parse_fecha(text: str) -> date | None:
    t = (text or "").strip()
    if not t:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _item(group: str, title: str, subtitle: str, url: str) -> dict[str, str]:
    return {"group": group, "title": title, "subtitle": subtitle, "url": url}


def _buscar_productos(q: str, q_cf: str, monto: Decimal | None) -> list[dict[str, str]]:
    filt = Q(descripcion__icontains=q) | Q(codigo__icontains=q) | Q(laboratorio__icontains=q)
    if monto is not None:
        filt |= Q(precio_venta=monto) | Q(costo=monto)
    qs = Producto.objects.filter(filt).order_by("descripcion")[:MAX_PER_GROUP]
    base = reverse("productos_list")
    out = []
    for p in qs:
        sub = f"{p.codigo} · {p.get_tipo_display()}"
        if p.laboratorio:
            sub += f" · {p.laboratorio}"
        out.append(
            _item(
                "Productos",
                p.descripcion[:120],
                sub,
                f"{base}?{urlencode({'q': q})}",
            )
        )
    return out


def _buscar_compradores(q: str, q_cf: str) -> list[dict[str, str]]:
    qs = (
        Comprador.objects.filter(
            Q(nombre__icontains=q)
            | Q(apellido__icontains=q)
            | Q(codigo__icontains=q)
            | Q(dni__icontains=q)
            | Q(mail__icontains=q)
        )
        .order_by("apellido", "nombre")[:MAX_PER_GROUP]
    )
    base = reverse("compradores_list")
    return [
        _item(
            "Compradores",
            f"{c.apellido}, {c.nombre}",
            c.codigo,
            f"{base}?{urlencode({'q': q})}",
        )
        for c in qs
    ]


def _buscar_presupuestos(q: str, q_cf: str, *, vendedor: Vendedor | None, solo_mi: bool) -> list[dict[str, str]]:
    filt = (
        Q(comprador__nombre__icontains=q)
        | Q(comprador__apellido__icontains=q)
        | Q(comprador__codigo__icontains=q)
        | Q(vendedor__nombre__icontains=q)
        | Q(vendedor__apellido__icontains=q)
    )
    if q.isdigit():
        filt |= Q(pk=int(q))
    qs = Presupuesto.objects.select_related("comprador", "vendedor").filter(filt)
    if solo_mi and vendedor is not None:
        qs = qs.filter(vendedor_id=vendedor.pk)
    qs = qs.order_by("-creado_en")[:MAX_PER_GROUP]
    out = []
    for pr in qs:
        comprador = (
            f"{pr.comprador.apellido}, {pr.comprador.nombre}" if pr.comprador_id else "Sin comprador"
        )
        out.append(
            _item(
                "Presupuestos",
                f"Presupuesto #{pr.pk}",
                f"{comprador} · {pr.get_estado_display()}",
                reverse("presupuesto_detalle", kwargs={"pk": pr.pk}),
            )
        )
    return out


def _buscar_gastos_compartidos(q: str, q_cf: str, monto: Decimal | None, fecha: date | None) -> list[dict[str, str]]:
    op_filt = (
        Q(concepto__icontains=q)
        | Q(observaciones__icontains=q)
        | Q(pagador__nombre__icontains=q)
        | Q(deudas__deudor__nombre__icontains=q)
    )
    if monto is not None:
        op_filt |= Q(monto_total=monto) | Q(deudas__monto=monto)
    if fecha is not None:
        op_filt |= Q(fecha=fecha)
    if q.isdigit():
        op_filt |= Q(pk=int(q))

    ops = (
        OperacionCompartida.objects.filter(op_filt)
        .select_related("pagador")
        .distinct()
        .order_by("-fecha", "-id")[:MAX_PER_GROUP]
    )
    dash = reverse("cuentas_dashboard")
    out = []
    for op in ops:
        out.append(
            _item(
                "Gastos compartidos",
                f"{op.get_tipo_display()}: {op.concepto}",
                f"{op.fecha:%d/%m/%Y} · pagó {op.pagador.nombre}",
                reverse("cuentas_operacion_detalle", kwargs={"pk": op.pk}),
            )
        )

    can_filt = (
        Q(detalle__icontains=q)
        | Q(deuda__deudor__nombre__icontains=q)
        | Q(deuda__operacion__pagador__nombre__icontains=q)
        | Q(deuda__operacion__concepto__icontains=q)
    )
    if monto is not None:
        can_filt |= Q(monto=monto)
    if fecha is not None:
        can_filt |= Q(fecha=fecha)

    cans = (
        CancelacionDeuda.objects.filter(can_filt)
        .select_related("deuda", "deuda__deudor", "deuda__operacion", "deuda__operacion__pagador")
        .order_by("-fecha", "-id")[: max(1, MAX_PER_GROUP - len(out))]
    )
    for c in cans:
        op = c.deuda.operacion
        out.append(
            _item(
                "Gastos compartidos",
                f"Cancelación: {c.deuda.deudor.nombre} → {op.pagador.nombre}",
                f"{c.fecha:%d/%m/%Y} · {c.get_medio_display()} · {c.monto}",
                reverse("cuentas_operacion_detalle", kwargs={"pk": op.pk}),
            )
        )

    if not out:
        params = {"q": q}
        if fecha is not None:
            params["al"] = fecha.isoformat()
        out.append(
            _item(
                "Gastos compartidos",
                "Buscar en cuenta corriente",
                f"Filtrar movimientos por «{q}»",
                f"{dash}?{urlencode(params)}",
            )
        )
    return out[:MAX_PER_GROUP]


def global_search_results(
    user,
    query: str,
    *,
    vendor_mode: bool = False,
    vendedor: Vendedor | None = None,
) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if len(q) < MIN_QUERY_LEN:
        return []
    q_cf = q.casefold()
    monto = _parse_monto(q)
    fecha = _parse_fecha(q)

    results: list[dict[str, str]] = []
    solo_mi = bool(vendor_mode or (vendedor is not None and not getattr(user, "is_staff", False)))

    if not vendor_mode:
        results.extend(_buscar_productos(q, q_cf, monto))
        results.extend(_buscar_compradores(q, q_cf))

    results.extend(_buscar_presupuestos(q, q_cf, vendedor=vendedor, solo_mi=solo_mi))

    if puede_usar_cuentas_compartidas(user):
        results.extend(_buscar_gastos_compartidos(q, q_cf, monto, fecha))

    return results[:24]
