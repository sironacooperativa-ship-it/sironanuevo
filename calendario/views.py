from datetime import date, datetime, timedelta
import calendar

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Min, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.export_utils import parse_export, pdf_response, xlsx_response

from caja.models import MovimientoCaja
from productos.models import Producto

from .forms import EventoForm
from .models import Evento

_CAL_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _add_months(d: date, n: int) -> date:
    m0 = d.month - 1 + n
    y = d.year + m0 // 12
    m = m0 % 12 + 1
    return date(y, m, 1)


def _meses_export_opciones() -> list[dict[str, str]]:
    """Lista de meses calendario (desde primer evento o 2020 hasta +24 meses desde hoy)."""
    lo = Evento.objects.aggregate(m=Min("fecha"))["m"]
    start = date(2020, 1, 1)
    if lo:
        start = min(start, lo.replace(day=1))
    end = _add_months(date.today().replace(day=1), 24)
    opts: list[dict[str, str]] = []
    cur = start
    while cur <= end:
        opts.append(
            {
                "key": f"{cur.year}-{cur.month}",
                "label": f"{_CAL_MESES[cur.month - 1].capitalize()} {cur.year}",
            }
        )
        cur = _add_months(cur, 1)
    return opts


def _parse_mes_keys(post_list: list[str]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for raw in post_list:
        parts = (raw or "").strip().split("-", 2)
        if len(parts) != 2:
            continue
        if not parts[0].isdigit() or not parts[1].isdigit():
            continue
        y, mo = int(parts[0]), int(parts[1])
        if 2000 <= y <= 2100 and 1 <= mo <= 12:
            out.append((y, mo))
    return sorted(set(out))


def _build_calendario_pdf_sections(meses: list[tuple[int, int]]) -> list[tuple[str, list[str], list[list]]]:
    sections: list[tuple[str, list[str], list[list]]] = []
    h_ev = ["Fecha", "Título", "Tipo", "Descripción"]
    h_ch = ["Vencimiento cheque", "Operación", "Nº cheque", "Monto", "Fecha mov."]
    h_ve = ["Vencimiento", "Código", "Producto", "Stock"]
    for y, mo in meses:
        fd = date(y, mo, 1)
        ld = date(y, mo, calendar.monthrange(y, mo)[1])
        label = f"{_CAL_MESES[mo - 1].capitalize()} {y}"
        eventos = Evento.objects.filter(fecha__range=(fd, ld)).order_by("fecha", "id")
        r_ev = [
            [
                e.fecha.strftime("%d/%m/%Y"),
                e.titulo,
                e.get_tipo_display(),
                (e.descripcion or "").replace("\n", " ")[:500],
            ]
            for e in eventos
        ]
        sections.append((f"{label} — Eventos", h_ev, r_ev))
        cheques = (
            MovimientoCaja.objects.filter(
                medio_pago=MovimientoCaja.MedioPago.CHEQUE,
                fecha_vencimiento_cheque__isnull=False,
                fecha_vencimiento_cheque__range=(fd, ld),
            )
            .select_related("vendedor")
            .order_by("fecha_vencimiento_cheque", "id")
        )
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
        sections.append((f"{label} — Vencimientos de cheques", h_ch, r_ch))
        vencimientos = Producto.objects.filter(
            fecha_vencimiento__isnull=False, fecha_vencimiento__range=(fd, ld)
        ).order_by("fecha_vencimiento", "descripcion", "codigo")
        r_ve = [
            [
                p.fecha_vencimiento.strftime("%d/%m/%Y") if p.fecha_vencimiento else "",
                p.codigo,
                p.descripcion,
                p.stock,
            ]
            for p in vencimientos
        ]
        sections.append((f"{label} — Vencimientos de medicamentos", h_ve, r_ve))
    return sections


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
    if exp == "pdf":
        messages.info(request, "Elegí uno o más meses para armar el PDF del calendario.")
        return redirect("calendario_export_pdf")
    if exp == "xlsx":
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
            ("Eventos", h_ev, r_ev),
            ("Cheques", h_ch, r_ch),
            ("Venc. productos", h_ve, r_ve),
        ]
        title = f"Calendario ({desde.strftime('%d/%m/%Y')} — {hasta.strftime('%d/%m/%Y')})"
        return xlsx_response("calendario", sheets)

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


@login_required
@require_http_methods(["GET", "POST"])
def calendario_export_pdf(request):
    if request.method == "POST":
        meses = _parse_mes_keys(request.POST.getlist("mes"))
        if not meses:
            messages.warning(request, "Elegí al menos un mes para exportar.")
            return redirect("calendario_export_pdf")
        sections = _build_calendario_pdf_sections(meses)
        return pdf_response("calendario_sirona", "Calendario Sirona", sections, body_fontsize=7)
    return render(
        request,
        "calendario/exportar_pdf.html",
        {"meses_opciones": _meses_export_opciones()},
    )

