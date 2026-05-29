from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q, Sum
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from core.export_utils import parse_export, pdf_response, xlsx_response

from .auth import cuentas_compartidas_required, modo_admin_gastos_required
from .forms import CancelacionDeudaForm, NegocioForm, OperacionCompartidaForm
from .models import (
    CancelacionDeuda,
    DeudaCompartida,
    MovimientoCCMarcacion,
    Negocio,
    OperacionCompartida,
)

CC_PAGE_SIZE = 25
CC_MOV_OPERACION = MovimientoCCMarcacion.MovTipo.OPERACION
CC_MOV_CANCELACION = MovimientoCCMarcacion.MovTipo.CANCELACION


def _fecha_corte_desde_request(request) -> date:
    hoy = date.today()
    raw = (request.GET.get("al") or "").strip()
    if not raw:
        return hoy
    try:
        y, m, d = (int(x) for x in raw.split("-"))
        fc = date(y, m, d)
    except (ValueError, TypeError):
        return hoy
    max_futuro = hoy + timedelta(days=365 * 5)
    if fc > max_futuro:
        return max_futuro
    return fc


def _deudas_con_saldo(queryset, *, fecha_corte: date):
    deudas = list(
        queryset.filter(operacion__fecha__lte=fecha_corte)
        .select_related("operacion", "operacion__pagador", "deudor")
        .annotate(
            pagado_calc=Sum(
                "cancelaciones__monto",
                filter=Q(cancelaciones__fecha__lte=fecha_corte),
            )
        )
        .order_by("vencimiento", "id")
    )
    for deuda in deudas:
        deuda.pagado_calc = deuda.pagado_calc or Decimal("0.00")
        deuda.pendiente_calc = max(deuda.monto - deuda.pagado_calc, Decimal("0.00"))
    return [deuda for deuda in deudas if deuda.pendiente_calc > 0]


def _saldos_netos(deudas, *, fecha_corte: date, par_ids: set[int] | None = None):
    dirigidos_hoy = defaultdict(Decimal)
    dirigidos_futuro = defaultdict(Decimal)
    nombres = {}
    for deuda in deudas:
        acreedor = deuda.operacion.pagador
        deudor = deuda.deudor
        if par_ids and {acreedor.pk, deudor.pk} != par_ids:
            continue
        dirigidos = dirigidos_hoy if deuda.vencimiento <= fecha_corte else dirigidos_futuro
        dirigidos[(deudor.pk, acreedor.pk)] += deuda.pendiente_calc
        nombres[deudor.pk] = deudor.nombre
        nombres[acreedor.pk] = acreedor.nombre

    pares = set(dirigidos_hoy.keys()) | set(dirigidos_futuro.keys())
    procesados = set()
    def balance_para(neto: Decimal, deudor_id: int, acreedor_id: int):
        if neto > 0:
            return {
                "deudor": nombres[deudor_id],
                "acreedor": nombres[acreedor_id],
                "deudor_id": deudor_id,
                "acreedor_id": acreedor_id,
                "monto": neto,
            }
        if neto < 0:
            return {
                "deudor": nombres[acreedor_id],
                "acreedor": nombres[deudor_id],
                "deudor_id": acreedor_id,
                "acreedor_id": deudor_id,
                "monto": abs(neto),
            }
        return None

    saldos = []
    for deudor_id, acreedor_id in pares:
        if (deudor_id, acreedor_id) in procesados:
            continue
        hoy_directo = dirigidos_hoy.get((deudor_id, acreedor_id), Decimal("0.00"))
        hoy_inverso = dirigidos_hoy.get((acreedor_id, deudor_id), Decimal("0.00"))
        futuro_directo = dirigidos_futuro.get((deudor_id, acreedor_id), Decimal("0.00"))
        futuro_inverso = dirigidos_futuro.get((acreedor_id, deudor_id), Decimal("0.00"))
        neto_hoy = hoy_directo - hoy_inverso
        neto_futuro = futuro_directo - futuro_inverso
        neto_total = neto_hoy + neto_futuro
        procesados.add((deudor_id, acreedor_id))
        procesados.add((acreedor_id, deudor_id))

        saldo_hoy = balance_para(neto_hoy, deudor_id, acreedor_id)
        saldo_futuro = balance_para(neto_futuro, deudor_id, acreedor_id)
        saldo_total = balance_para(neto_total, deudor_id, acreedor_id)
        if not saldo_hoy and not saldo_futuro and not saldo_total:
            continue

        saldos.append(
            {
                "negocio_a": nombres[deudor_id],
                "negocio_b": nombres[acreedor_id],
                "saldo_hoy": saldo_hoy,
                "saldo_futuro": saldo_futuro,
                "saldo_total": saldo_total,
            }
        )
    return sorted(saldos, key=lambda item: (item["negocio_a"], item["negocio_b"]))


def _saldos_pares(deudas, *, fecha_corte: date, par_ids: set[int] | None = None) -> list[dict]:
    """Saldos netos entre pares en una sola dirección: deudor le debe a acreedor."""
    filas = []
    for item in _saldos_netos(deudas, fecha_corte=fecha_corte, par_ids=par_ids):
        total = item.get("saldo_total")
        if not total:
            continue
        exigible = item.get("saldo_hoy") or {}
        futuro = item.get("saldo_futuro") or {}
        filas.append(
            {
                "deudor": total["deudor"],
                "acreedor": total["acreedor"],
                "deudor_id": total["deudor_id"],
                "acreedor_id": total["acreedor_id"],
                "monto": total["monto"],
                "monto_exigible": exigible.get("monto") or Decimal("0.00"),
                "monto_sin_vencer": futuro.get("monto") or Decimal("0.00"),
            }
        )
    return sorted(filas, key=lambda row: (-row["monto"], row["deudor"], row["acreedor"]))


def _filtro_par_desde_request(request) -> tuple[str, str, set[int] | None, list[Negocio]]:
    todos_negocios = list(Negocio.objects.order_by("nombre"))
    negocio_a = (request.GET.get("negocio_a") or "").strip()
    negocio_b = (request.GET.get("negocio_b") or "").strip()
    par_ids = None
    negocios = todos_negocios
    if negocio_a.isdigit() and negocio_b.isdigit() and negocio_a != negocio_b:
        par_ids = {int(negocio_a), int(negocio_b)}
        negocios_filtrados = [n for n in todos_negocios if n.pk in par_ids]
        if len(negocios_filtrados) == 2:
            negocios = negocios_filtrados
        else:
            par_ids = None
    return negocio_a, negocio_b, par_ids, todos_negocios, negocios


def _puede_editar_operacion(request, operacion: OperacionCompartida) -> bool:
    if request.user.is_staff and request.session.get("modo_admin"):
        return True
    return bool(operacion.creado_por_id and operacion.creado_por_id == request.user.pk)


def _negocios_para_operacion(operacion: OperacionCompartida | None = None) -> list[Negocio]:
    qs = Negocio.objects.filter(activo=True)
    if operacion and operacion.pk:
        ids = {operacion.pagador_id}
        ids.update(operacion.deudas.values_list("deudor_id", flat=True))
        qs = Negocio.objects.filter(pk__in=ids) | qs
    return list(qs.distinct().order_by("nombre"))


def _deudas_cambiaron(operacion: OperacionCompartida, nuevas: list[dict]) -> bool:
    actuales = {
        deuda.deudor_id: (Decimal(deuda.monto), deuda.vencimiento)
        for deuda in operacion.deudas.all()
    }
    propuestas = {
        item["negocio"].pk: (Decimal(item["monto"]), item["vencimiento"])
        for item in nuevas
    }
    return actuales != propuestas


def _deuda_rows(form: OperacionCompartidaForm, negocios: list[Negocio]) -> list[dict]:
    return [
        {
            "negocio": negocio,
            "incluir": form[f"incluir_{negocio.pk}"],
            "monto": form[f"monto_{negocio.pk}"],
            "vencimiento": form[f"vencimiento_{negocio.pk}"],
        }
        for negocio in negocios
    ]


def _guardar_deudas_operacion(operacion: OperacionCompartida, deudas: list[dict]) -> None:
    operacion.deudas.all().delete()
    for item in deudas:
        DeudaCompartida.objects.create(
            operacion=operacion,
            deudor=item["negocio"],
            monto=item["monto"],
            vencimiento=item["vencimiento"],
        )


def _marcaciones_cc_map() -> dict[tuple[str, int], bool]:
    return {
        (m.mov_tipo, m.objeto_id): m.marcado
        for m in MovimientoCCMarcacion.objects.all().only("mov_tipo", "objeto_id", "marcado")
    }


def _archivar_movimiento_cc(mov_tipo: str, objeto_id: int, *, user, archivado: bool = True) -> None:
    if archivado:
        MovimientoCCMarcacion.objects.update_or_create(
            mov_tipo=mov_tipo,
            objeto_id=objeto_id,
            defaults={"marcado": True, "marcado_por": user},
        )
    else:
        MovimientoCCMarcacion.objects.filter(mov_tipo=mov_tipo, objeto_id=objeto_id).delete()


def _deuda_pendiente_al(deuda: DeudaCompartida, fecha_corte: date) -> Decimal:
    pagado = (
        deuda.cancelaciones.filter(fecha__lte=fecha_corte).aggregate(total=Sum("monto"))["total"]
        or Decimal("0.00")
    )
    return max(Decimal(deuda.monto or 0) - pagado, Decimal("0.00"))


def _operacion_tiene_pendiente(operacion: OperacionCompartida, fecha_corte: date) -> bool:
    for deuda in operacion.deudas.all():
        if _deuda_pendiente_al(deuda, fecha_corte) > 0:
            return True
    return False


def _cc_estado_desde_request(request) -> str:
    estado = (request.GET.get("estado") or "").strip().lower()
    if estado in ("pendiente", "archivado", "todos"):
        return estado
    marcado = (request.GET.get("marcado") or "").strip().lower()
    if marcado == "si":
        return "archivado"
    if marcado == "no":
        return "pendiente"
    return "pendiente"


def _parse_cc_seleccion(post) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for raw in post.getlist("seleccion"):
        if ":" not in raw:
            continue
        mov_tipo, oid = raw.split(":", 1)
        if mov_tipo in (CC_MOV_OPERACION, CC_MOV_CANCELACION) and oid.isdigit():
            out.append((mov_tipo, int(oid)))
    return out


def _cuenta_corriente_rows(
    negocios: list[Negocio], *, par_ids: set[int] | None = None, fecha_corte: date
):
    negocios_ids = [negocio.pk for negocio in negocios]
    marcaciones = _marcaciones_cc_map()
    rows = []
    totales = {negocio.pk: Decimal("0.00") for negocio in negocios}

    operaciones = (
        OperacionCompartida.objects.filter(fecha__lte=fecha_corte)
        .select_related("pagador")
        .prefetch_related("deudas", "deudas__deudor")
        .order_by("fecha", "id")
    )
    for operacion in operaciones:
        valores = {negocio_id: Decimal("0.00") for negocio_id in negocios_ids}
        total_asignado = Decimal("0.00")
        partes = []
        for deuda in operacion.deudas.all():
            if par_ids and {operacion.pagador_id, deuda.deudor_id} != par_ids:
                continue
            monto = Decimal(deuda.monto or 0)
            total_asignado += monto
            if deuda.deudor_id in valores:
                valores[deuda.deudor_id] -= monto
            partes.append(f"{deuda.deudor.nombre}: {monto}")
        if total_asignado <= 0:
            continue
        if operacion.pagador_id in valores:
            valores[operacion.pagador_id] += total_asignado

        for negocio_id, monto in valores.items():
            totales[negocio_id] += monto

        mov_key = (CC_MOV_OPERACION, operacion.pk)
        archivado = marcaciones.get(mov_key, False)
        rows.append(
            {
                "fecha": operacion.fecha,
                "orden": operacion.pk * 2,
                "detalle": f"{operacion.get_tipo_display()}: {operacion.concepto}",
                "subdetalle": f"Pagó {operacion.pagador.nombre}. Partes: {', '.join(partes) if partes else '—'}",
                "url": "cuentas_operacion_detalle",
                "url_pk": operacion.pk,
                "mov_tipo": CC_MOV_OPERACION,
                "mov_id": operacion.pk,
                "archivado": archivado,
                "puede_pagar": _operacion_tiene_pendiente(operacion, fecha_corte),
                "seleccion": f"{CC_MOV_OPERACION}:{operacion.pk}",
                "valores": [valores[negocio.pk] for negocio in negocios],
            }
        )

    cancelaciones = (
        CancelacionDeuda.objects.filter(fecha__lte=fecha_corte)
        .select_related("deuda", "deuda__deudor", "deuda__operacion", "deuda__operacion__pagador")
        .order_by("fecha", "id")
    )
    for cancelacion in cancelaciones:
        deuda = cancelacion.deuda
        acreedor = deuda.operacion.pagador
        deudor = deuda.deudor
        if par_ids and {acreedor.pk, deudor.pk} != par_ids:
            continue
        monto = Decimal(cancelacion.monto or 0)
        valores = {negocio_id: Decimal("0.00") for negocio_id in negocios_ids}
        if deudor.pk in valores:
            valores[deudor.pk] += monto
        if acreedor.pk in valores:
            valores[acreedor.pk] -= monto

        for negocio_id, valor in valores.items():
            totales[negocio_id] += valor

        mov_key = (CC_MOV_CANCELACION, cancelacion.pk)
        archivado = marcaciones.get(mov_key, False)
        rows.append(
            {
                "fecha": cancelacion.fecha,
                "orden": cancelacion.pk * 2 + 1,
                "detalle": f"Cancelación: {deudor.nombre} a {acreedor.nombre}",
                "subdetalle": f"{cancelacion.get_medio_display()}{f' · {cancelacion.detalle}' if cancelacion.detalle else ''}",
                "url": "cuentas_operacion_detalle",
                "url_pk": deuda.operacion_id,
                "mov_tipo": CC_MOV_CANCELACION,
                "mov_id": cancelacion.pk,
                "archivado": archivado,
                "puede_pagar": False,
                "seleccion": f"{CC_MOV_CANCELACION}:{cancelacion.pk}",
                "valores": [valores[negocio.pk] for negocio in negocios],
            }
        )

    return rows, [totales[negocio.pk] for negocio in negocios]


def _cuenta_corriente_ord_keys(negocios: list[Negocio]) -> set[str]:
    keys = {"fecha", "detalle"}
    keys.update(f"n{negocio.pk}" for negocio in negocios)
    return keys


def _ordenar_cuenta_corriente_rows(
    rows: list[dict], request, negocios: list[Negocio]
) -> tuple[list[dict], str, str]:
    ord_keys = _cuenta_corriente_ord_keys(negocios)
    ord_key = (request.GET.get("ord") or "").strip()
    dir_raw = (request.GET.get("dir") or "").strip().lower()
    if dir_raw not in ("asc", "desc"):
        dir_raw = "asc"

    negocio_idx = {negocio.pk: idx for idx, negocio in enumerate(negocios)}

    def default_sort():
        rows.sort(key=lambda row: (row["fecha"], row["orden"]), reverse=True)

    if ord_key not in ord_keys:
        default_sort()
        return rows, "", "desc"

    if ord_key == "fecha":
        key = lambda row: (row["fecha"], row["orden"])
    elif ord_key == "detalle":
        key = lambda row: (row["detalle"].casefold(), row["orden"])
    else:
        idx = negocio_idx[int(ord_key[1:])]
        key = lambda row: (row["valores"][idx], row["orden"])

    rows.sort(key=key, reverse=(dir_raw == "desc"))
    return rows, ord_key, dir_raw


def _cuenta_corriente_sort_links(request, negocios: list[Negocio]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _cuenta_corriente_ord_keys(negocios):
        q = request.GET.copy()
        cur_o = (request.GET.get("ord") or "").strip()
        cur_d = (request.GET.get("dir") or "asc").strip().lower()
        if cur_d not in ("asc", "desc"):
            cur_d = "asc"
        if cur_o == key:
            q["ord"] = key
            q["dir"] = "desc" if cur_d == "asc" else "asc"
        else:
            q["ord"] = key
            q["dir"] = "asc"
        out[key] = q.urlencode()
    return out


def _cuenta_corriente_url_sin_orden(request) -> str:
    q = request.GET.copy()
    q.pop("ord", None)
    q.pop("dir", None)
    return q.urlencode()


def _parse_busqueda_monto(text: str):
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


def _filtrar_cuenta_corriente_por_q(rows: list[dict], q: str) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return rows
    q_cf = q.casefold()
    monto_q = _parse_busqueda_monto(q)
    out = []
    for row in rows:
        if q_cf in row["detalle"].casefold() or q_cf in row["subdetalle"].casefold():
            out.append(row)
            continue
        fecha = row["fecha"]
        if q_cf in fecha.strftime("%d/%m/%Y").casefold() or q in fecha.isoformat():
            out.append(row)
            continue
        if monto_q is not None:
            for valor in row["valores"]:
                if valor != 0 and abs(abs(valor) - monto_q) < Decimal("0.01"):
                    out.append(row)
                    break
    return out


def _filtrar_cuenta_corriente_por_estado(rows: list[dict], estado: str) -> list[dict]:
    if estado == "archivado":
        return [row for row in rows if row.get("archivado")]
    if estado == "pendiente":
        return [row for row in rows if not row.get("archivado")]
    return rows


def _cuenta_corriente_totales_desde_filas(rows: list[dict], n_cols: int) -> list[Decimal]:
    totales = [Decimal("0.00")] * n_cols
    for row in rows:
        for i, valor in enumerate(row["valores"]):
            totales[i] += valor
    return totales


def _cuenta_corriente_preparada(
    request, negocios: list[Negocio], *, par_ids: set[int] | None, fecha_corte: date
):
    rows, totales = _cuenta_corriente_rows(negocios, par_ids=par_ids, fecha_corte=fecha_corte)
    rows, cc_sort_ord, cc_sort_dir = _ordenar_cuenta_corriente_rows(rows, request, negocios)
    cc_q = (request.GET.get("q") or "").strip()
    if cc_q:
        rows = _filtrar_cuenta_corriente_por_q(rows, cc_q)
    cc_estado = _cc_estado_desde_request(request)
    if cc_estado in ("pendiente", "archivado"):
        rows = _filtrar_cuenta_corriente_por_estado(rows, cc_estado)
        totales = _cuenta_corriente_totales_desde_filas(rows, len(negocios))
    return rows, totales, cc_sort_ord, cc_sort_dir, cc_q, cc_estado


def _cc_export_querystring(request) -> str:
    q = request.GET.copy()
    q.pop("page", None)
    return q.urlencode()


def _cuenta_corriente_context(request) -> dict:
    hoy = date.today()
    fecha_corte = _fecha_corte_desde_request(request)
    es_hoy = fecha_corte == hoy
    negocio_a, negocio_b, par_ids, todos_negocios, negocios = _filtro_par_desde_request(request)
    cuenta_corriente_rows, cuenta_corriente_totales, cc_sort_ord, cc_sort_dir, cc_q, cc_estado = (
        _cuenta_corriente_preparada(request, negocios, par_ids=par_ids, fecha_corte=fecha_corte)
    )
    cc_paginator = Paginator(cuenta_corriente_rows, CC_PAGE_SIZE)
    cc_page = cc_paginator.get_page(request.GET.get("page") or 1)
    cc_sort_links = _cuenta_corriente_sort_links(request, negocios)
    negocios_cc_columnas = [
        {
            "negocio": negocio,
            "sort_ord": f"n{negocio.pk}",
            "sort_link": cc_sort_links[f"n{negocio.pk}"],
        }
        for negocio in negocios
    ]
    return {
        "negocios": negocios,
        "todos_negocios": todos_negocios,
        "filtro_negocio_a": negocio_a,
        "filtro_negocio_b": negocio_b,
        "filtro_par_activo": bool(par_ids),
        "fecha_corte": fecha_corte,
        "fecha_corte_iso": fecha_corte.isoformat(),
        "fecha_hoy_iso": hoy.isoformat(),
        "es_hoy": es_hoy,
        "fecha_max_futuro_iso": (hoy + timedelta(days=365 * 5)).isoformat(),
        "cuenta_corriente_rows": cc_page.object_list,
        "cuenta_corriente_page": cc_page,
        "cuenta_corriente_totales": cuenta_corriente_totales,
        "cc_sort_ord": cc_sort_ord,
        "cc_sort_dir": cc_sort_dir,
        "cc_q": cc_q,
        "cc_estado": cc_estado,
        "cc_acciones_url": reverse("cuentas_cuenta_corriente_acciones"),
        "cc_sort_links": cc_sort_links,
        "negocios_cc_columnas": negocios_cc_columnas,
        "cc_querystring_sin_orden": _cuenta_corriente_url_sin_orden(request),
        "cc_export_query": _cc_export_querystring(request),
        "puede_admin_gastos_compartidos": bool(
            request.user.is_staff and request.session.get("modo_admin")
        ),
        "puede_cargar_gastos_compartidos": True,
    }


@cuentas_compartidas_required
def cuentas_dashboard(request):
    hoy = date.today()
    fecha_corte = _fecha_corte_desde_request(request)
    es_hoy = fecha_corte == hoy
    es_futuro = fecha_corte > hoy
    negocio_a, negocio_b, par_ids, todos_negocios, _negocios = _filtro_par_desde_request(request)
    deudas_pendientes = _deudas_con_saldo(DeudaCompartida.objects.all(), fecha_corte=fecha_corte)
    saldos_pares = _saldos_pares(deudas_pendientes, fecha_corte=fecha_corte, par_ids=par_ids)
    total_pendiente = sum((p["monto"] for p in saldos_pares), Decimal("0.00"))
    return render(
        request,
        "cuentas_compartidas/dashboard.html",
        {
            "todos_negocios": todos_negocios,
            "filtro_negocio_a": negocio_a,
            "filtro_negocio_b": negocio_b,
            "filtro_par_activo": bool(par_ids),
            "fecha_corte": fecha_corte,
            "fecha_corte_iso": fecha_corte.isoformat(),
            "fecha_hoy_iso": hoy.isoformat(),
            "es_hoy": es_hoy,
            "es_futuro": es_futuro,
            "fecha_max_futuro_iso": (hoy + timedelta(days=365 * 5)).isoformat(),
            "saldos_pares": saldos_pares,
            "total_pendiente": total_pendiente,
            "puede_admin_gastos_compartidos": bool(
                request.user.is_staff and request.session.get("modo_admin")
            ),
            "puede_cargar_gastos_compartidos": True,
        },
    )


@cuentas_compartidas_required
def cuenta_corriente(request):
    ctx = _cuenta_corriente_context(request)
    return render(request, "cuentas_compartidas/cuenta_corriente.html", ctx)


@cuentas_compartidas_required
@require_http_methods(["GET"])
def cuenta_corriente_export(request):
    exp = parse_export(request)
    if exp not in ("xlsx", "pdf"):
        q = _cc_export_querystring(request)
        url = reverse("cuentas_cuenta_corriente")
        return redirect(f"{url}?{q}" if q else url)

    hoy = date.today()
    fecha_corte = _fecha_corte_desde_request(request)
    todos_negocios = list(Negocio.objects.order_by("nombre"))
    negocio_a = (request.GET.get("negocio_a") or "").strip()
    negocio_b = (request.GET.get("negocio_b") or "").strip()
    par_ids = None
    negocios = todos_negocios
    if negocio_a.isdigit() and negocio_b.isdigit() and negocio_a != negocio_b:
        par_ids = {int(negocio_a), int(negocio_b)}
        negocios_filtrados = [n for n in todos_negocios if n.pk in par_ids]
        if len(negocios_filtrados) == 2:
            negocios = negocios_filtrados
        else:
            par_ids = None

    rows, totales, _, _, cc_q, cc_estado = _cuenta_corriente_preparada(
        request, negocios, par_ids=par_ids, fecha_corte=fecha_corte
    )
    headers = ["Estado", "Fecha", "Detalle", "Subdetalle"] + [n.nombre for n in negocios]
    data_rows = []
    for row in rows:
        vals = []
        for v in row["valores"]:
            vals.append("" if v == 0 else str(v))
        data_rows.append(
            [
                "Archivado" if row.get("archivado") else "Pendiente",
                row["fecha"].strftime("%d/%m/%Y"),
                row["detalle"],
                row["subdetalle"],
                *vals,
            ]
        )
    tot_row = ["", "", "Saldo total (movimientos listados)", ""]
    for t in totales:
        tot_row.append("" if t == 0 else str(t))
    data_rows.append(tot_row)

    titulo = f"Cuenta corriente — Gastos compartidos (al {fecha_corte:%d/%m/%Y})"
    if cc_q:
        titulo += f" — búsqueda: {cc_q}"
    if cc_estado == "archivado":
        titulo += " — solo archivados"
    elif cc_estado == "pendiente":
        titulo += " — solo pendientes"
    fname = f"gastos_compartidos_cc_{fecha_corte.isoformat()}"

    if exp == "xlsx":
        return xlsx_response(fname, [("Cuenta corriente", headers, data_rows)])
    return pdf_response(fname, titulo, [("Movimientos", headers, data_rows)])


def _puede_eliminar_movimiento_cc(request, mov_tipo: str, objeto_id: int) -> bool:
    if request.user.is_staff and request.session.get("modo_admin"):
        return True
    if mov_tipo == CC_MOV_OPERACION:
        operacion = OperacionCompartida.objects.filter(pk=objeto_id).first()
        return bool(operacion and _puede_editar_operacion(request, operacion))
    return False


def _marcar_movimiento_pagado(
    mov_tipo: str, objeto_id: int, *, user, fecha_pago: date
) -> tuple[bool, str]:
    if mov_tipo == CC_MOV_OPERACION:
        operacion = (
            OperacionCompartida.objects.filter(pk=objeto_id)
            .prefetch_related("deudas", "deudas__cancelaciones")
            .first()
        )
        if not operacion:
            return False, "Operación no encontrada."
        pagos = 0
        for deuda in operacion.deudas.all():
            pendiente = deuda.pendiente
            if pendiente <= 0:
                continue
            cancelacion = CancelacionDeuda(
                deuda=deuda,
                fecha=fecha_pago,
                monto=pendiente,
                medio=CancelacionDeuda.Medio.DINERO,
                detalle="Pago registrado (acción masiva)",
            )
            cancelacion.full_clean()
            cancelacion.save()
            pagos += 1
        _archivar_movimiento_cc(mov_tipo, objeto_id, user=user, archivado=True)
        if pagos:
            return True, f"Operación #{objeto_id}: {pagos} deuda(s) cancelada(s)."
        return True, f"Operación #{objeto_id}: archivada (ya estaba pagada)."
    if mov_tipo == CC_MOV_CANCELACION:
        if not CancelacionDeuda.objects.filter(pk=objeto_id).exists():
            return False, "Cancelación no encontrada."
        _archivar_movimiento_cc(mov_tipo, objeto_id, user=user, archivado=True)
        return True, f"Cancelación #{objeto_id} archivada."
    return False, "Movimiento inválido."


def _eliminar_movimiento_cc(request, mov_tipo: str, objeto_id: int) -> tuple[bool, str]:
    if not _puede_eliminar_movimiento_cc(request, mov_tipo, objeto_id):
        return False, "No tenés permiso para eliminar este movimiento."
    if mov_tipo == CC_MOV_OPERACION:
        operacion = OperacionCompartida.objects.filter(pk=objeto_id).first()
        if not operacion:
            return False, "Operación no encontrada."
        concepto = operacion.concepto
        operacion.delete()
        MovimientoCCMarcacion.objects.filter(mov_tipo=mov_tipo, objeto_id=objeto_id).delete()
        return True, f"Operación eliminada: {concepto}."
    if mov_tipo == CC_MOV_CANCELACION:
        cancelacion = CancelacionDeuda.objects.filter(pk=objeto_id).first()
        if not cancelacion:
            return False, "Cancelación no encontrada."
        cancelacion.delete()
        MovimientoCCMarcacion.objects.filter(mov_tipo=mov_tipo, objeto_id=objeto_id).delete()
        return True, "Cancelación eliminada."
    return False, "Movimiento inválido."


@modo_admin_gastos_required
@require_POST
def cuenta_corriente_acciones(request):
    accion = (request.POST.get("accion") or "").strip().lower()
    if accion not in ("pagar", "eliminar"):
        messages.error(request, "Acción no válida.")
        return redirect(_dashboard_redirect_con_query(request))

    seleccion = _parse_cc_seleccion(request)
    if not seleccion:
        messages.warning(request, "Seleccioná al menos un movimiento.")
        return redirect(_dashboard_redirect_con_query(request))

    fecha_pago = date.today()
    ok_n = 0
    errores: list[str] = []
    for mov_tipo, objeto_id in seleccion:
        if accion == "pagar":
            ok, msg = _marcar_movimiento_pagado(
                mov_tipo, objeto_id, user=request.user, fecha_pago=fecha_pago
            )
        else:
            ok, msg = _eliminar_movimiento_cc(request, mov_tipo, objeto_id)
        if ok:
            ok_n += 1
        else:
            errores.append(msg)

    if ok_n:
        if accion == "pagar":
            messages.success(
                request,
                f"{ok_n} movimiento{'s' if ok_n != 1 else ''} marcado{'s' if ok_n != 1 else ''} como pagado{'s' if ok_n != 1 else ''} y archivado{'s' if ok_n != 1 else ''}.",
            )
        else:
            messages.success(
                request,
                f"{ok_n} movimiento{'s' if ok_n != 1 else ''} eliminado{'s' if ok_n != 1 else ''}.",
            )
    if errores:
        messages.error(request, " · ".join(errores[:5]))
    return redirect(_dashboard_redirect_con_query(request))


def _dashboard_redirect_con_query(request) -> str:
    from urllib.parse import parse_qsl

    from django.http import QueryDict

    raw = (request.POST.get("retorno_query") or "").strip()
    if raw:
        qd = QueryDict(mutable=True)
        for k, v in parse_qsl(raw, keep_blank_values=True):
            if v:
                qd[k] = v
    else:
        qd = request.GET.copy()
    if "estado" not in qd and "marcado" not in qd:
        qd["estado"] = "pendiente"
    url = reverse("cuentas_cuenta_corriente")
    qs = qd.urlencode()
    return f"{url}?{qs}" if qs else url


@cuentas_compartidas_required
@require_http_methods(["GET", "POST"])
def operacion_nueva(request):
    negocios = _negocios_para_operacion()
    if len(negocios) < 2:
        messages.warning(request, "Cargá al menos dos negocios activos antes de registrar una operación.")
        return redirect("cuentas_negocios")

    if request.method == "POST":
        form = OperacionCompartidaForm(request.POST, negocios=negocios)
        if form.is_valid():
            with transaction.atomic():
                operacion = form.save(commit=False)
                operacion.creado_por = request.user
                operacion.save()
                _guardar_deudas_operacion(operacion, form.cleaned_data["deudas"])
            messages.success(request, "Operación compartida registrada.")
            return redirect("cuentas_dashboard")
    else:
        form = OperacionCompartidaForm(
            negocios=negocios,
            initial={"fecha": date.today(), "tipo": OperacionCompartida.Tipo.COMPRA},
        )
    return render(
        request,
        "cuentas_compartidas/operacion_form.html",
        {"form": form, "deuda_rows": _deuda_rows(form, negocios), "modo": "nuevo"},
    )


@cuentas_compartidas_required
@require_http_methods(["GET", "POST"])
def operacion_editar(request, pk: int):
    operacion = get_object_or_404(
        OperacionCompartida.objects.prefetch_related("deudas", "deudas__cancelaciones"),
        pk=pk,
    )
    if not _puede_editar_operacion(request, operacion):
        raise PermissionDenied("Solo puede editar este gasto quien lo cargó.")

    negocios = _negocios_para_operacion(operacion)
    tiene_cancelaciones = CancelacionDeuda.objects.filter(deuda__operacion=operacion).exists()
    if request.method == "POST":
        form = OperacionCompartidaForm(request.POST, instance=operacion, negocios=negocios)
        if form.is_valid():
            deudas_cambiaron = _deudas_cambiaron(operacion, form.cleaned_data["deudas"])
            if tiene_cancelaciones and deudas_cambiaron:
                form.add_error(None, "Este gasto ya tiene cancelaciones. Podés editar los datos generales, pero no el reparto.")
            else:
                with transaction.atomic():
                    operacion = form.save()
                    if not tiene_cancelaciones and deudas_cambiaron:
                        _guardar_deudas_operacion(operacion, form.cleaned_data["deudas"])
                messages.success(request, "Gasto compartido actualizado.")
                return redirect("cuentas_operacion_detalle", pk=operacion.pk)
    else:
        form = OperacionCompartidaForm(instance=operacion, negocios=negocios)
    return render(
        request,
        "cuentas_compartidas/operacion_form.html",
        {
            "form": form,
            "deuda_rows": _deuda_rows(form, negocios),
            "modo": "editar",
            "operacion": operacion,
            "tiene_cancelaciones": tiene_cancelaciones,
        },
    )


@cuentas_compartidas_required
def operacion_detalle(request, pk: int):
    operacion = get_object_or_404(
        OperacionCompartida.objects.select_related("pagador").prefetch_related("deudas", "deudas__deudor", "deudas__cancelaciones"),
        pk=pk,
    )
    return render(
        request,
        "cuentas_compartidas/operacion_detalle.html",
        {
            "operacion": operacion,
            "puede_admin_gastos_compartidos": bool(request.user.is_staff and request.session.get("modo_admin")),
            "puede_editar_operacion": _puede_editar_operacion(request, operacion),
        },
    )


@modo_admin_gastos_required
@require_http_methods(["GET", "POST"])
def cancelar_deuda(request, pk: int):
    deuda = get_object_or_404(DeudaCompartida.objects.select_related("operacion", "operacion__pagador", "deudor"), pk=pk)
    if deuda.esta_pagada:
        messages.info(request, "Esta deuda ya está cancelada.")
        return redirect("cuentas_dashboard")
    if request.method == "POST":
        form = CancelacionDeudaForm(request.POST, deuda=deuda)
        if form.is_valid():
            cancelacion: CancelacionDeuda = form.save(commit=False)
            cancelacion.deuda = deuda
            cancelacion.full_clean()
            cancelacion.save()
            messages.success(request, "Cancelación registrada.")
            return redirect("cuentas_dashboard")
    else:
        form = CancelacionDeudaForm(deuda=deuda, initial={"fecha": date.today(), "monto": deuda.pendiente})
    return render(request, "cuentas_compartidas/cancelacion_form.html", {"form": form, "deuda": deuda})


@modo_admin_gastos_required
@require_http_methods(["GET", "POST"])
def negocios(request):
    if request.method == "POST":
        form = NegocioForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Negocio guardado.")
            return redirect("cuentas_negocios")
    else:
        form = NegocioForm(initial={"activo": True})
    return render(
        request,
        "cuentas_compartidas/negocios.html",
        {"form": form, "negocios": Negocio.objects.order_by("nombre")},
    )


@modo_admin_gastos_required
@require_http_methods(["GET", "POST"])
def negocio_editar(request, pk: int):
    negocio = get_object_or_404(Negocio, pk=pk)
    if request.method == "POST":
        form = NegocioForm(request.POST, instance=negocio)
        if form.is_valid():
            form.save()
            messages.success(request, "Negocio actualizado.")
            return redirect("cuentas_negocios")
    else:
        form = NegocioForm(instance=negocio)
    return render(
        request,
        "cuentas_compartidas/negocio_form.html",
        {"form": form, "negocio": negocio},
    )


@modo_admin_gastos_required
@require_http_methods(["POST"])
def negocio_eliminar(request, pk: int):
    negocio = get_object_or_404(Negocio, pk=pk)
    nombre = negocio.nombre
    try:
        negocio.delete()
    except ProtectedError:
        negocio.activo = False
        negocio.save(update_fields=["activo"])
        messages.warning(
            request,
            f"No se puede eliminar {nombre} porque ya tiene movimientos. Lo dejé inactivo para que no aparezca en nuevas operaciones.",
        )
    else:
        messages.success(request, f"Negocio eliminado: {nombre}.")
    return redirect("cuentas_negocios")
