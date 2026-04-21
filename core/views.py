from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
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


def _safe_get_vendedor_perfil(user) -> Vendedor | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        v = user.vendedor_perfil
        return v if isinstance(v, Vendedor) else None
    except ObjectDoesNotExist:
        return None


@login_required
def home(request):
    # Si el usuario está en modo vendedor, mostrar un inicio reducido con datos propios (también si es staff).
    modo_v = bool(request.session.get("modo_vendedor", False))
    solo_v = bool(getattr(getattr(request.user, "perfil_acceso", None), "solo_vendedor", False))
    if modo_v or solo_v:
        v = getattr(request.user, "vendedor_perfil", None)
        if v is not None:
            today = timezone.localdate()
            ult_30 = today - timedelta(days=29)

            neto_expr = ExpressionWrapper(
                F("subtotal_lineas") - F("descuento_monto"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
            neto_nonneg = Case(
                When(subtotal_lineas__gte=F("descuento_monto"), then=neto_expr),
                default=Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
            ventas_30 = Venta.objects.filter(vendedor_id=v.pk, creado_en__date__gte=ult_30)
            kpis = ventas_30.aggregate(
                pedidos=Count("id"),
                neto_total=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))),
                pagadas=Count("id", filter=Q(estado=Venta.Estado.PAGADA)),
                pendientes=Count("id", filter=Q(estado=Venta.Estado.PENDIENTE)),
            )
            kpis["neto_total"] = q2(kpis["neto_total"])

            pendientes = (
                Venta.objects.filter(vendedor_id=v.pk, estado=Venta.Estado.PENDIENTE)
                .select_related("comprador")
                .order_by("fecha_vencimiento_pago", "id")[:25]
            )
            return render(
                request,
                "core/home_vendedor.html",
                {"vendedor": v, "kpis_ventas": kpis, "ventas_pendientes": pendientes, "hoy": today},
            )

    today = timezone.localdate()
    ult_30 = today - timedelta(days=29)
    prox_7 = today + timedelta(days=7)
    prox_30 = today + timedelta(days=30)
    prox_90 = today + timedelta(days=90)
    prox_180 = today + timedelta(days=180)

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

    cheques_a_pagar = (
        MovimientoCaja.objects.filter(
            tipo=MovimientoCaja.Tipo.EGRESO,
            medio_pago=MovimientoCaja.MedioPago.CHEQUE,
            fecha_vencimiento_cheque__isnull=False,
            fecha_vencimiento_cheque__gte=today,
            fecha_vencimiento_cheque__lte=prox_30,
        )
        .order_by("fecha_vencimiento_cheque", "id")[:50]
    )

    stock_critico = Producto.objects.filter(habilitado=True, stock__lte=0).order_by("descripcion", "codigo")[:30]
    vencimientos_prod = (
        Producto.objects.filter(habilitado=True, fecha_vencimiento__isnull=False, fecha_vencimiento__lte=prox_30)
        .order_by("fecha_vencimiento", "descripcion", "codigo")[:30]
    )

    meds_venc_90 = (
        Producto.objects.filter(
            tipo=Producto.Tipo.MEDICAMENTOS,
            fecha_vencimiento__isnull=False,
            fecha_vencimiento__gte=today,
            fecha_vencimiento__lte=prox_90,
        )
        .order_by("fecha_vencimiento", "descripcion", "codigo")[:50]
    )
    meds_venc_180 = (
        Producto.objects.filter(
            tipo=Producto.Tipo.MEDICAMENTOS,
            fecha_vencimiento__isnull=False,
            fecha_vencimiento__gt=prox_90,
            fecha_vencimiento__lte=prox_180,
        )
        .order_by("fecha_vencimiento", "descripcion", "codigo")[:50]
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
            "cheques_a_pagar": cheques_a_pagar,
            "stock_critico": stock_critico,
            "vencimientos_prod": vencimientos_prod,
            "meds_venc_90": meds_venc_90,
            "meds_venc_180": meds_venc_180,
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
    # El checkbox se muestra en el login; si el usuario no puede o no aplica, se ignora.
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
                solo_vendedor = bool(
                    getattr(getattr(user, "perfil_acceso", None), "solo_vendedor", False)
                )
                entrar = (request.POST.get("entrar_como_vendedor") or "0") == "1"
                # Importante: NO autocrear ni autovincular vendedor (evita duplicados).
                v = _safe_get_vendedor_perfil(user)

                # Guardar modo en sesión (para menú/layout). Staff puede entrar como vendedor con el checkbox.
                modo = bool(solo_vendedor or (entrar and v is not None))
                request.session["modo_vendedor"] = modo

                if solo_vendedor:
                    if v is None:
                        messages.error(request, "Tu usuario está marcado como 'solo vendedor' pero no tiene perfil de vendedor asignado.")
                        logout(request)
                        return redirect("login")
                    return redirect("vendedor_home")
                if entrar and v is not None:
                    return redirect("vendedor_home")
                if entrar and v is None:
                    messages.error(request, "Este usuario no tiene perfil de vendedor asignado.")
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
    try:
        request.session.pop("modo_vendedor", None)
    except Exception:
        pass
    return redirect("login")


@login_required
@require_http_methods(["GET"])
def switch_to_vendor_mode(request):
    # Si ya es solo_vendedor, el modo viene dado por perfil; pero igual marcamos sesión para el layout.
    solo_vendedor = bool(getattr(getattr(request.user, "perfil_acceso", None), "solo_vendedor", False))
    v = _safe_get_vendedor_perfil(request.user)
    if (solo_vendedor or v is not None) and v is not None:
        request.session["modo_vendedor"] = True
        return redirect("vendedor_home")

    messages.error(request, "Este usuario no tiene perfil de vendedor.")
    return redirect("home")


@login_required
@require_http_methods(["GET"])
def switch_to_full_mode(request):
    # Solo permitir salir del modo vendedor a quienes no son 'solo_vendedor'
    solo_vendedor = bool(getattr(getattr(request.user, "perfil_acceso", None), "solo_vendedor", False))
    if solo_vendedor:
        return redirect("vendedor_home")
    try:
        request.session["modo_vendedor"] = False
        request.session.pop("modo_vendedor", None)
    except Exception:
        pass
    return redirect("home")


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

