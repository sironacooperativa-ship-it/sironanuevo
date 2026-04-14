from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from core.export_utils import parse_export, pdf_response, xlsx_response

from caja.models import MovimientoCaja
from productos.models import Producto

from .forms import EventoForm
from .models import Evento


@login_required
@require_http_methods(["GET", "POST"])
def calendario_home(request):
    if request.method == "POST":
        form = EventoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Evento guardado.")
            return redirect("calendario_home")
    else:
        form = EventoForm()

    desde = date.today()
    hasta = desde + timedelta(days=90)

    cheques = (
        MovimientoCaja.objects.filter(
            medio_pago=MovimientoCaja.MedioPago.CHEQUE,
            fecha_vencimiento_cheque__isnull=False,
            fecha_vencimiento_cheque__range=(desde, hasta),
        )
        .select_related("vendedor")
        .order_by("fecha_vencimiento_cheque", "id")
    )

    vencimientos = Producto.objects.filter(
        fecha_vencimiento__isnull=False, fecha_vencimiento__range=(desde, hasta)
    ).order_by("fecha_vencimiento", "codigo")

    eventos = Evento.objects.filter(fecha__range=(desde, hasta)).order_by("fecha", "id")

    # búsqueda simple
    q = (request.GET.get("q") or "").strip()
    if q:
        eventos = eventos.filter(Q(titulo__icontains=q) | Q(descripcion__icontains=q))

    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        h_ch = ["Vencimiento cheque", "Operación", "Nº cheque", "Monto", "Fecha mov."]
        r_ch = [
            [
                m.fecha_vencimiento_cheque.strftime("%d/%m/%Y") if m.fecha_vencimiento_cheque else "",
                m.operacion,
                m.numero_cheque,
                str(m.monto),
                m.fecha.strftime("%d/%m/%Y"),
            ]
            for m in cheques
        ]
        h_ve = ["Vencimiento", "Código", "Producto", "Stock"]
        r_ve = [
            [
                p.fecha_vencimiento.strftime("%d/%m/%Y") if p.fecha_vencimiento else "",
                p.codigo,
                p.descripcion,
                p.stock,
            ]
            for p in vencimientos
        ]
        h_ev = ["Fecha", "Título", "Tipo", "Descripción"]
        r_ev = [
            [
                e.fecha.strftime("%d/%m/%Y"),
                e.titulo,
                e.get_tipo_display(),
                (e.descripcion or "").replace("\n", " ")[:500],
            ]
            for e in eventos
        ]
        sheets = [
            ("Cheques", h_ch, r_ch),
            ("Venc. productos", h_ve, r_ve),
            ("Eventos", h_ev, r_ev),
        ]
        title = f"Calendario ({desde.strftime('%d/%m/%Y')} — {hasta.strftime('%d/%m/%Y')})"
        if exp == "xlsx":
            return xlsx_response("calendario", sheets)
        return pdf_response("calendario", title, sheets)

    return render(
        request,
        "calendario/home.html",
        {
            "form": form,
            "desde": desde,
            "hasta": hasta,
            "cheques": cheques,
            "vencimientos": vencimientos,
            "eventos": eventos,
            "q": q,
        },
    )

