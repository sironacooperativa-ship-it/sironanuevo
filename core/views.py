from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import connections
from django.db.utils import OperationalError
from django.http import HttpResponse
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import SironaPasswordChangeForm
from .money_decimal import q2

from calendario.models import Evento
from caja.models import MovimientoCaja
from compras.models import Compra
from productos.models import Producto
from ventas.models import Venta

from administrador.models import RegistroActividad
from personas.models import Vendedor


def _safe_relative_next(path: str) -> str:
    """
    Evita redirecciones abiertas: solo permite rutas internas relativas.
    Acepta solo strings que empiezan con '/' y rechaza '//' (scheme-relative).
    """
    if not path:
        return ""
    path = str(path).strip()
    if not path.startswith("/") or path.startswith("//"):
        return ""
    return path


@login_required
def home(request):
    today = timezone.localdate()
    ult_30 = today - timedelta(days=29)
    prox_7 = today + timedelta(days=7)
    prox_30 = today + timedelta(days=30)

    pendientes = (
        Venta.objects.filter(estado=Venta.Estado.PENDIENTE)
        .select_related("vendedor")
        .order_by("fecha_vencimiento_pago", "id")[:25]
    )

    neto_expr = ExpressionWrapper(
        F("subtotal_lineas") - F("descuento_monto"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    neto_nonneg = Case(
        When(subtotal_lineas__gte=F("descuento_monto"), then=neto_expr),
        default=Value(Decimal("0.00")),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    ventas_30 = Venta.objects.filter(creado_en__date__gte=ult_30)
    kpis_ventas = ventas_30.aggregate(
        pedidos=Count("id"),
        neto_total=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))),
        pagadas=Count("id", filter=Q(estado=Venta.Estado.PAGADA)),
        pendientes=Count("id", filter=Q(estado=Venta.Estado.PENDIENTE)),
    )
    kpis_ventas["neto_total"] = q2(kpis_ventas["neto_total"])
    compras_30 = Compra.objects.filter(fecha_compra__gte=ult_30)
    kpis_compras = compras_30.aggregate(
        compras=Count("id"),
        monto_total=Coalesce(Sum("monto"), Value(Decimal("0.00"))),
    )
    kpis_compras["monto_total"] = q2(kpis_compras["monto_total"])

    recordatorios = Evento.objects.filter(fecha__gte=today, fecha__lte=prox_7).order_by("fecha", "id")[:30]
    hoy_recordatorios = Evento.objects.filter(fecha=today).order_by("tipo", "id")[:50]
    hoy_pagos = (
        Venta.objects.filter(estado=Venta.Estado.PENDIENTE, fecha_vencimiento_pago=today)
        .select_related("vendedor")
        .order_by("id")[:50]
    )
    cheques = (
        MovimientoCaja.objects.filter(
            medio_pago=MovimientoCaja.MedioPago.CHEQUE,
            fecha_vencimiento_cheque__isnull=False,
            fecha_vencimiento_cheque__gte=today,
            fecha_vencimiento_cheque__lte=prox_7,
        )
        .order_by("fecha_vencimiento_cheque", "id")[:30]
    )
    hoy_cheques = (
        MovimientoCaja.objects.filter(
            medio_pago=MovimientoCaja.MedioPago.CHEQUE,
            fecha_vencimiento_cheque=today,
        )
        .order_by("id")[:50]
    )

    stock_critico = Producto.objects.filter(habilitado=True, stock__lte=0).order_by("descripcion", "codigo")[:30]
    vencimientos_prod = (
        Producto.objects.filter(habilitado=True, fecha_vencimiento__isnull=False, fecha_vencimiento__lte=prox_30)
        .order_by("fecha_vencimiento", "descripcion", "codigo")[:30]
    )

    _tipo_labels = dict(Producto.Tipo.choices)
    por_tipo_rows = (
        Producto.objects.values("tipo").annotate(total=Count("id")).order_by("tipo")
    )
    resumen = {
        "productos_total": Producto.objects.count(),
        "productos_habilitados": Producto.objects.filter(habilitado=True).count(),
        "productos_deshabilitados": Producto.objects.filter(habilitado=False).count(),
        "productos_en_lista": Producto.objects.filter(en_lista_precios=True, habilitado=True).count(),
        "por_tipo": [
            {
                "tipo": row["tipo"],
                "tipo_nombre": _tipo_labels.get(row["tipo"], row["tipo"]),
                "total": row["total"],
            }
            for row in por_tipo_rows
        ],
    }
    return render(
        request,
        "core/home.html",
        {
            "resumen": resumen,
            "ventas_pendientes": pendientes,
            "kpis_ventas": kpis_ventas,
            "kpis_compras": kpis_compras,
            "recordatorios": recordatorios,
            "hoy_recordatorios": hoy_recordatorios,
            "hoy_pagos": hoy_pagos,
            "hoy_cheques": hoy_cheques,
            "cheques_proximos": cheques,
            "stock_critico": stock_critico,
            "vencimientos_prod": vencimientos_prod,
            "hoy": today,
        },
    )


@require_http_methods(["GET"])
def health(request):
    return HttpResponse("ok", content_type="text/plain")


@require_http_methods(["GET"])
def warmup(request):
    try:
        conn = connections["default"]
        conn.ensure_connection()
    except OperationalError:
        return HttpResponse("db_error", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    next_url = _safe_relative_next(request.GET.get("next") or "")
    idle_timeout = request.GET.get("idle") == "1" or request.POST.get("idle") == "1"

    error = None
    # El checkbox se muestra en el login; si el usuario no es vendedor o no aplica, se ignora.
    vendedor_option_visible = True
    vendedor_option_checked = False
    vendedor_option_locked = False
    if request.method == "POST":
        next_url = _safe_relative_next(request.POST.get("next") or "") or next_url
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if next_url:
                return redirect(next_url)
            try:
                v = getattr(user, "vendedor_perfil", None)
                if v is not None and not user.is_staff:
                    # Política:
                    # - SOLO_VENDEDOR: siempre portal
                    # - SOLO_COMPLETO: siempre home
                    # - AMBOS: depende del checkbox del login
                    if getattr(v, "acceso", None) == Vendedor.Acceso.SOLO_VENDEDOR:
                        return redirect("vendedor_home")
                    if getattr(v, "acceso", None) == Vendedor.Acceso.SOLO_COMPLETO:
                        return redirect("home")
                    entrar = (request.POST.get("entrar_como_vendedor") or "0") == "1"
                    if entrar:
                        return redirect("vendedor_home")
            except Exception:
                pass
            return redirect("home")
        error = "Usuario o contraseña incorrectos."

    return render(
        request,
        "core/login.html",
        {
            "error": error,
            "idle_timeout": idle_timeout,
            "next": next_url,
            "vendedor_option_visible": vendedor_option_visible,
            "vendedor_option_checked": vendedor_option_checked,
            "vendedor_option_locked": vendedor_option_locked,
        },
    )


def logout_view(request):
    if request.user.is_authenticated:
        try:
            RegistroActividad.registrar_cierre_sesion(request.user, request)
        except Exception:
            # No bloquear el cierre de sesión si falla el registro (p. ej. IP inválida / BD)
            pass
    logout(request)
    return redirect("login")


@login_required
@require_http_methods(["GET", "POST"])
def cambiar_password(request):
    if request.method == "POST":
        form = SironaPasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Tu contraseña fue actualizada.")
            return redirect("home")
    else:
        form = SironaPasswordChangeForm(user=request.user)

    return render(request, "core/cambiar_password.html", {"form": form})

