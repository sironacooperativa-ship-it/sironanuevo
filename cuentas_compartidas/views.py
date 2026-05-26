from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .auth import cuentas_compartidas_required, modo_admin_gastos_required
from .forms import CancelacionDeudaForm, NegocioForm, OperacionCompartidaForm
from .models import CancelacionDeuda, DeudaCompartida, Negocio, OperacionCompartida


def _deudas_con_saldo(queryset):
    deudas = list(
        queryset.select_related("operacion", "operacion__pagador", "deudor")
        .annotate(pagado_calc=Sum("cancelaciones__monto"))
        .order_by("vencimiento", "id")
    )
    for deuda in deudas:
        deuda.pagado_calc = deuda.pagado_calc or Decimal("0.00")
        deuda.pendiente_calc = max(deuda.monto - deuda.pagado_calc, Decimal("0.00"))
    return [deuda for deuda in deudas if deuda.pendiente_calc > 0]


def _saldos_netos(deudas):
    dirigidos = defaultdict(Decimal)
    nombres = {}
    for deuda in deudas:
        acreedor = deuda.operacion.pagador
        deudor = deuda.deudor
        dirigidos[(deudor.pk, acreedor.pk)] += deuda.pendiente_calc
        nombres[deudor.pk] = deudor.nombre
        nombres[acreedor.pk] = acreedor.nombre

    procesados = set()
    saldos = []
    for (deudor_id, acreedor_id), monto in dirigidos.items():
        if (deudor_id, acreedor_id) in procesados:
            continue
        inverso = dirigidos.get((acreedor_id, deudor_id), Decimal("0.00"))
        neto = monto - inverso
        procesados.add((deudor_id, acreedor_id))
        procesados.add((acreedor_id, deudor_id))
        if neto > 0:
            saldos.append({"deudor": nombres[deudor_id], "acreedor": nombres[acreedor_id], "monto": neto})
        elif neto < 0:
            saldos.append({"deudor": nombres[acreedor_id], "acreedor": nombres[deudor_id], "monto": abs(neto)})
    return sorted(saldos, key=lambda item: (item["deudor"], item["acreedor"]))


def _cuenta_corriente_rows(negocios: list[Negocio], *, par_ids: set[int] | None = None):
    negocios_ids = [negocio.pk for negocio in negocios]
    rows = []
    totales = {negocio.pk: Decimal("0.00") for negocio in negocios}

    operaciones = (
        OperacionCompartida.objects.select_related("pagador")
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

        rows.append(
            {
                "fecha": operacion.fecha,
                "orden": operacion.pk * 2,
                "detalle": f"{operacion.get_tipo_display()}: {operacion.concepto}",
                "subdetalle": f"Pagó {operacion.pagador.nombre}. Partes: {', '.join(partes) if partes else '—'}",
                "url": "cuentas_operacion_detalle",
                "url_pk": operacion.pk,
                "valores": [valores[negocio.pk] for negocio in negocios],
            }
        )

    cancelaciones = (
        CancelacionDeuda.objects.select_related("deuda", "deuda__deudor", "deuda__operacion", "deuda__operacion__pagador")
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

        rows.append(
            {
                "fecha": cancelacion.fecha,
                "orden": cancelacion.pk * 2 + 1,
                "detalle": f"Cancelación: {deudor.nombre} a {acreedor.nombre}",
                "subdetalle": f"{cancelacion.get_medio_display()}{f' · {cancelacion.detalle}' if cancelacion.detalle else ''}",
                "url": "cuentas_operacion_detalle",
                "url_pk": deuda.operacion_id,
                "valores": [valores[negocio.pk] for negocio in negocios],
            }
        )

    rows.sort(key=lambda row: (row["fecha"], row["orden"]), reverse=True)
    return rows, [totales[negocio.pk] for negocio in negocios]


@cuentas_compartidas_required
def cuentas_dashboard(request):
    hoy = date.today()
    todos_negocios = list(Negocio.objects.order_by("nombre"))
    negocio_a = (request.GET.get("negocio_a") or "").strip()
    negocio_b = (request.GET.get("negocio_b") or "").strip()
    par_ids = None
    negocios = todos_negocios
    if negocio_a.isdigit() and negocio_b.isdigit() and negocio_a != negocio_b:
        par_ids = {int(negocio_a), int(negocio_b)}
        negocios_filtrados = [negocio for negocio in todos_negocios if negocio.pk in par_ids]
        if len(negocios_filtrados) == 2:
            negocios = negocios_filtrados
        else:
            par_ids = None
    deudas_pendientes = _deudas_con_saldo(DeudaCompartida.objects.all())
    vencimientos = sorted(deudas_pendientes, key=lambda deuda: (deuda.vencimiento, deuda.pk))[:12]
    vencidas = [deuda for deuda in deudas_pendientes if deuda.vencimiento < hoy]
    proximas = [deuda for deuda in deudas_pendientes if hoy <= deuda.vencimiento <= hoy + timedelta(days=14)]
    cuenta_corriente_rows, cuenta_corriente_totales = _cuenta_corriente_rows(negocios, par_ids=par_ids)
    return render(
        request,
        "cuentas_compartidas/dashboard.html",
        {
            "negocios": negocios,
            "todos_negocios": todos_negocios,
            "filtro_negocio_a": negocio_a,
            "filtro_negocio_b": negocio_b,
            "filtro_par_activo": bool(par_ids),
            "saldos": _saldos_netos(deudas_pendientes),
            "vencimientos": vencimientos,
            "vencidas": vencidas,
            "proximas": proximas,
            "cuenta_corriente_rows": cuenta_corriente_rows,
            "cuenta_corriente_totales": cuenta_corriente_totales,
            "total_pendiente": sum((deuda.pendiente_calc for deuda in deudas_pendientes), Decimal("0.00")),
            "puede_editar_gastos_compartidos": bool(request.user.is_staff and request.session.get("modo_admin")),
        },
    )


@modo_admin_gastos_required
@require_http_methods(["GET", "POST"])
def operacion_nueva(request):
    negocios = list(Negocio.objects.filter(activo=True).order_by("nombre"))
    if len(negocios) < 2:
        messages.warning(request, "Cargá al menos dos negocios activos antes de registrar una operación.")
        return redirect("cuentas_negocios")

    if request.method == "POST":
        form = OperacionCompartidaForm(request.POST, negocios=negocios)
        if form.is_valid():
            with transaction.atomic():
                operacion = form.save()
                for item in form.cleaned_data["deudas"]:
                    DeudaCompartida.objects.create(
                        operacion=operacion,
                        deudor=item["negocio"],
                        monto=item["monto"],
                        vencimiento=item["vencimiento"],
                    )
            messages.success(request, "Operación compartida registrada.")
            return redirect("cuentas_dashboard")
    else:
        form = OperacionCompartidaForm(
            negocios=negocios,
            initial={"fecha": date.today(), "tipo": OperacionCompartida.Tipo.COMPRA},
        )
    deuda_rows = [
        {
            "negocio": negocio,
            "incluir": form[f"incluir_{negocio.pk}"],
            "monto": form[f"monto_{negocio.pk}"],
            "vencimiento": form[f"vencimiento_{negocio.pk}"],
        }
        for negocio in negocios
    ]
    return render(request, "cuentas_compartidas/operacion_form.html", {"form": form, "deuda_rows": deuda_rows})


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
            "puede_editar_gastos_compartidos": bool(request.user.is_staff and request.session.get("modo_admin")),
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
