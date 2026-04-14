from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from caja.models import MovimientoCaja

from core.export_utils import parse_export, pdf_response, xlsx_response

from .forms import AjusteCuentaForm, CuentaBancariaForm, GastoTransferenciaForm
from .models import CuentaBancaria, Gasto, MovimientoCuentaBancaria


@login_required
def bancos_cuentas(request):
    cuentas = CuentaBancaria.con_saldo_actual()
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = ["Banco", "Cuenta", "Saldo inicial", "Saldo actual", "Activa"]
        rows = [
            [c.banco, c.cuenta, str(c.saldo_inicial), str(c.saldo_actual), "Sí" if c.activa else "No"]
            for c in cuentas
        ]
        if exp == "xlsx":
            return xlsx_response("bancos_cuentas", [("Cuentas", headers, rows)])
        return pdf_response("bancos_cuentas", "Cuentas bancarias", [("Cuentas", headers, rows)])
    return render(request, "bancos/cuenta_list.html", {"cuentas": cuentas})


@login_required
@require_http_methods(["GET", "POST"])
def banco_cuenta_nueva(request):
    if request.method == "POST":
        form = CuentaBancariaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Cuenta bancaria creada.")
            return redirect("bancos_cuentas")
    else:
        form = CuentaBancariaForm(initial={"activa": True, "saldo_inicial": "0"})
    return render(request, "bancos/cuenta_form.html", {"form": form})


@login_required
def banco_cuenta_detalle(request, pk: int):
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)
    movs = list(
        MovimientoCuentaBancaria.objects.filter(cuenta=cuenta).select_related("movimiento_caja").order_by(
            "fecha", "id"
        )
    )
    saldo = cuenta.saldo_inicial
    rows = []
    for m in movs:
        delta = m.monto if m.credito else -m.monto
        saldo += delta
        rows.append({"m": m, "saldo": saldo})

    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = ["Fecha", "Origen", "Concepto", "Debe/Haber", "Monto", "Saldo"]
        er = []
        s = cuenta.saldo_inicial
        er.append(["—", "—", "Saldo inicial", "—", "—", str(s)])
        for m in movs:
            d = m.monto if m.credito else -m.monto
            s += d
            dh = "Haber (+)" if m.credito else "Debe (−)"
            er.append(
                [
                    m.fecha.strftime("%d/%m/%Y"),
                    m.get_origen_display(),
                    m.concepto,
                    dh,
                    str(m.monto),
                    str(s),
                ]
            )
        base = f"cuenta_{cuenta.pk}"
        tit = f"Movimientos — {cuenta.banco} ({cuenta.cuenta})"
        if exp == "xlsx":
            return xlsx_response(base, [("Movimientos", headers, er)])
        return pdf_response(base, tit, [("Movimientos", headers, er)])

    ajuste_form = AjusteCuentaForm(
        initial={"fecha": datetime.now().strftime("%d/%m/%y")},
    )
    return render(
        request,
        "bancos/cuenta_detail.html",
        {"cuenta": cuenta, "rows": rows, "saldo_final": saldo, "ajuste_form": ajuste_form},
    )


@login_required
@require_http_methods(["POST"])
def banco_cuenta_ajuste(request, pk: int):
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)
    form = AjusteCuentaForm(request.POST)
    if form.is_valid():
        cd = form.cleaned_data
        credito = cd["tipo"] == "CRE"
        MovimientoCuentaBancaria.objects.create(
            cuenta=cuenta,
            fecha=cd["fecha"],
            monto=cd["monto"],
            credito=credito,
            origen=MovimientoCuentaBancaria.Origen.AJUSTE,
            concepto=cd["concepto"].strip()[:255],
        )
        messages.success(request, "Ajuste registrado.")
    else:
        for field, errs in form.errors.items():
            for e in errs:
                messages.error(request, f"{field}: {e}")
    return redirect("banco_cuenta_detalle", pk=pk)


@login_required
def bancos_gastos(request):
    gastos = Gasto.objects.select_related("cuenta_bancaria", "movimiento_caja").order_by("-fecha", "-id")
    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = ["Fecha", "Descripción", "Cuenta", "Banco (cuenta)", "Monto", "Mov. caja id"]
        rows = [
            [
                g.fecha.strftime("%d/%m/%Y"),
                g.descripcion,
                g.cuenta_bancaria.cuenta,
                g.cuenta_bancaria.banco,
                str(g.monto),
                g.movimiento_caja_id,
            ]
            for g in gastos
        ]
        if exp == "xlsx":
            return xlsx_response("bancos_gastos", [("Gastos", headers, rows)])
        return pdf_response("bancos_gastos", "Gastos por transferencia", [("Gastos", headers, rows)])
    return render(request, "bancos/gasto_list.html", {"gastos": gastos})


@login_required
@require_http_methods(["GET", "POST"])
def banco_gasto_nuevo(request):
    if request.method == "POST":
        form = GastoTransferenciaForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            cb: CuentaBancaria = cd["cuenta_bancaria"]
            det = (cd.get("banco_detalle") or "").strip()
            banco_txt = f"{cb.banco} — {cb.cuenta}"[:100]
            if det:
                banco_txt = f"{banco_txt} ({det})"[:100]
            try:
                with transaction.atomic():
                    mov = MovimientoCaja(
                        fecha=cd["fecha"],
                        operacion=f"Gasto: {cd['descripcion'][:200]}",
                        tipo=MovimientoCaja.Tipo.EGRESO,
                        monto=cd["monto"],
                        medio_pago=MovimientoCaja.MedioPago.TRANSFERENCIA,
                        banco=banco_txt,
                        cuenta_bancaria=cb,
                    )
                    mov.full_clean()
                    mov.save()
                    Gasto.objects.create(
                        fecha=cd["fecha"],
                        descripcion=cd["descripcion"].strip(),
                        monto=cd["monto"],
                        cuenta_bancaria=cb,
                        movimiento_caja=mov,
                    )
            except ValidationError as exc:
                if getattr(exc, "error_dict", None):
                    for lst in exc.error_dict.values():
                        for m in lst:
                            messages.error(request, str(m))
                else:
                    for m in getattr(exc, "messages", [str(exc)]):
                        messages.error(request, str(m))
                return render(request, "bancos/gasto_form.html", {"form": form})
            except DatabaseError as exc:
                messages.error(request, str(exc))
                return render(request, "bancos/gasto_form.html", {"form": form})
            messages.success(request, "Gasto registrado (caja y cuenta bancaria).")
            return redirect("bancos_gastos")
    else:
        form = GastoTransferenciaForm(
            initial={"fecha": datetime.now().strftime("%d/%m/%y")},
        )
    return render(request, "bancos/gasto_form.html", {"form": form})


@login_required
@require_http_methods(["POST"])
def banco_gasto_eliminar(request, pk: int):
    gasto = get_object_or_404(Gasto.objects.select_related("movimiento_caja"), pk=pk)
    with transaction.atomic():
        mov = gasto.movimiento_caja
        gasto.delete()
        mov.delete()
    messages.success(request, "Gasto y movimiento de caja eliminados.")
    return redirect("bancos_gastos")
