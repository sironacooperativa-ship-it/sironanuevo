from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.export_utils import parse_export, pdf_response, xlsx_response

from caja.models import MovimientoCaja
from productos.models import Producto

from .forms import EventoForm
from .models import Evento


def _parse_iso_date(raw: str) -> date | None:
    s = (raw or "").strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_time(raw: str) -> datetime.time | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%H:%M").time()
    except Exception:
        return None


@login_required
@require_http_methods(["GET", "POST"])
def calendario_home(request):
    # Ventana de tiempo (días) y filtros de agenda.
    raw_w = (request.GET.get("w") or "").strip()
    window_days = 90
    if raw_w.isdigit():
        w = int(raw_w)
        if 7 <= w <= 365:
            window_days = w
    tipo = (request.GET.get("tipo") or "").strip().upper()
    tipos_validos = {k for (k, _) in Evento.Tipo.choices}
    if tipo and tipo not in tipos_validos:
        tipo = ""

    if request.method == "POST":
        form = EventoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Evento guardado.")
            retorno = (request.POST.get("retorno_query") or "").strip()
            if retorno:
                return redirect(f"{request.path}?{retorno}")
            return redirect("calendario_home")
    else:
        form = EventoForm()

    desde = date.today()
    hasta = desde + timedelta(days=window_days)

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
    ).order_by("fecha_vencimiento", "descripcion", "codigo")

    eventos = Evento.objects.filter(fecha__range=(desde, hasta)).order_by("fecha", "id")

    # búsqueda simple
    q = (request.GET.get("q") or "").strip()
    if q:
        eventos = eventos.filter(Q(titulo__icontains=q) | Q(descripcion__icontains=q))
    if tipo:
        eventos = eventos.filter(tipo=tipo)

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

    calendario_mes = {
        "hoy": date.today().isoformat(),
        "eventos": [
            {
                "id": e.pk,
                "fecha": e.fecha.isoformat(),
                "hora": e.hora.strftime("%H:%M") if e.hora else "",
                "titulo": (e.titulo or "")[:200],
                "tipo": e.tipo,
                "descripcion": (e.descripcion or "")[:1200],
                "realizado": bool(e.realizado),
            }
            for e in eventos
        ],
    }

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
            "tipo": tipo,
            "tipos": Evento.Tipo.choices,
            "window_days": window_days,
            "retorno_query": request.GET.urlencode(),
            "calendario_mes": calendario_mes,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def calendario_agenda_dia(request, iso: str):
    dia = _parse_iso_date(iso)
    if not dia:
        return HttpResponseBadRequest("Fecha inválida.")

    q = (request.GET.get("q") or "").strip()
    tipo = (request.GET.get("tipo") or "").strip().upper()
    tipos_validos = {k for (k, _) in Evento.Tipo.choices}
    if tipo and tipo not in tipos_validos:
        tipo = ""

    qs = Evento.objects.filter(fecha=dia).order_by("hora", "id")
    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(descripcion__icontains=q))
    if tipo:
        qs = qs.filter(tipo=tipo)

    if request.method == "POST":
        accion = (request.POST.get("accion") or "").strip()
        if accion == "create":
            hora = _parse_time(request.POST.get("hora") or "")
            titulo = (request.POST.get("titulo") or "").strip()[:255]
            tipo_new = (request.POST.get("tipo") or "").strip().upper()
            desc = (request.POST.get("descripcion") or "").strip()
            realizado = request.POST.get("realizado") in ("1", "true", "on", "yes")
            if not titulo:
                return HttpResponseBadRequest("Título requerido.")
            if tipo_new not in tipos_validos:
                tipo_new = Evento.Tipo.MANUAL
            Evento.objects.create(
                fecha=dia,
                hora=hora,
                titulo=titulo,
                tipo=tipo_new,
                descripcion=desc,
                realizado=realizado,
            )
        elif accion in ("toggle", "delete", "update"):
            rid = (request.POST.get("id") or "").strip()
            if not rid.isdigit():
                return HttpResponseBadRequest("ID inválido.")
            ev = get_object_or_404(Evento, pk=int(rid), fecha=dia)
            if accion == "toggle":
                ev.realizado = not bool(ev.realizado)
                ev.save(update_fields=["realizado"])
            elif accion == "delete":
                ev.delete()
            else:  # update
                ev.hora = _parse_time(request.POST.get("hora") or "")
                ev.titulo = (request.POST.get("titulo") or "").strip()[:255] or ev.titulo
                tipo_up = (request.POST.get("tipo") or "").strip().upper()
                if tipo_up in tipos_validos:
                    ev.tipo = tipo_up
                ev.descripcion = (request.POST.get("descripcion") or "").strip()
                ev.save(update_fields=["hora", "titulo", "tipo", "descripcion"])
        # refetch qs after changes
        qs = Evento.objects.filter(fecha=dia).order_by("hora", "id")
        if q:
            qs = qs.filter(Q(titulo__icontains=q) | Q(descripcion__icontains=q))
        if tipo:
            qs = qs.filter(tipo=tipo)

    eventos = list(qs)
    eventos_hora = [e for e in eventos if e.hora]
    eventos_sin_hora = [e for e in eventos if not e.hora]

    tipo_label = dict(Evento.Tipo.choices).get(tipo, "") if tipo else ""
    ctx = {
        "dia": dia,
        "eventos": eventos,
        "eventos_hora": eventos_hora,
        "eventos_sin_hora": eventos_sin_hora,
        "q": q,
        "tipo": tipo,
        "tipo_label": tipo_label,
        "tipos": Evento.Tipo.choices,
        "default_tipo": tipo or Evento.Tipo.MANUAL,
    }

    # Modal fragment only
    return render(request, "calendario/agenda_day_fragment.html", ctx)

