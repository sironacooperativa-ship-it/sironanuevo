from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .auth import cuentas_compartidas_required
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


@cuentas_compartidas_required
def cuentas_dashboard(request):
    hoy = date.today()
    deudas_pendientes = _deudas_con_saldo(DeudaCompartida.objects.all())
    vencimientos = sorted(deudas_pendientes, key=lambda deuda: (deuda.vencimiento, deuda.pk))[:12]
    vencidas = [deuda for deuda in deudas_pendientes if deuda.vencimiento < hoy]
    proximas = [deuda for deuda in deudas_pendientes if hoy <= deuda.vencimiento <= hoy + timedelta(days=14)]
    operaciones = (
        OperacionCompartida.objects.select_related("pagador").prefetch_related("deudas", "deudas__deudor").order_by("-fecha", "-id")[:10]
    )
    return render(
        request,
        "cuentas_compartidas/dashboard.html",
        {
            "saldos": _saldos_netos(deudas_pendientes),
            "vencimientos": vencimientos,
            "vencidas": vencidas,
            "proximas": proximas,
            "operaciones": operaciones,
            "total_pendiente": sum((deuda.pendiente_calc for deuda in deudas_pendientes), Decimal("0.00")),
        },
    )


@cuentas_compartidas_required
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
    return render(request, "cuentas_compartidas/operacion_detalle.html", {"operacion": operacion})


@cuentas_compartidas_required
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


@cuentas_compartidas_required
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
