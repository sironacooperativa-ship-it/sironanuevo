from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import connections, transaction
from django.db.utils import OperationalError
from django.http import HttpResponse, JsonResponse
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import SironaPasswordChangeForm
from .models import NotaAdmin
from .money_decimal import q2
from .security import client_ip, safe_internal_path

from calendario.models import Evento
from caja.models import MovimientoCaja
from compras.models import Compra
from productos.models import Producto
from ventas.models import Venta
from ventas.sql_metrics import venta_neto_nonneg_expr

from administrador.models import RegistroActividad
from personas.models import Vendedor


def _safe_get_vendedor_perfil(user) -> Vendedor | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        v = user.vendedor_perfil
        return v if isinstance(v, Vendedor) else None
    except ObjectDoesNotExist:
        return None


def _ensure_vendedor_perfil(user) -> Vendedor | None:
    """Devuelve o crea/enlaza un perfil vendedor para usuarios que alternan de modo."""
    v = _safe_get_vendedor_perfil(user)
    if v is not None:
        return v

    if user is None or not getattr(user, "is_authenticated", False):
        return None

    nombre = (getattr(user, "first_name", "") or "").strip() or (getattr(user, "username", "") or "").strip()
    apellido = (getattr(user, "last_name", "") or "").strip()
    candidatos = Vendedor.objects.filter(usuario__isnull=True, habilitado=True)

    existente = None
    if nombre and apellido:
        existente = candidatos.filter(nombre__iexact=nombre, apellido__iexact=apellido).first()
    if existente is None and nombre:
        matches = list(candidatos.filter(nombre__iexact=nombre)[:2])
        if len(matches) == 1:
            existente = matches[0]

    with transaction.atomic():
        if existente is not None:
            existente.usuario = user
            existente.save(update_fields=["usuario"])
            return existente

        return Vendedor.objects.create(
            nombre=nombre or getattr(user, "username", ""),
            apellido=apellido or "—",
            usuario=user,
            habilitado=True,
        )


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

            neto_nonneg = venta_neto_nonneg_expr()
            ventas_30 = Venta.objects.filter(vendedor_id=v.pk, creado_en__date__gte=ult_30)
            kpis = ventas_30.aggregate(
                pedidos=Count("id"),
                neto_total=Coalesce(Sum(neto_nonneg), Value(Decimal("0.00"))),
                pagadas=Count("id", filter=Q(estado=Venta.Estado.PAGADA)),
                pendientes=Count("id", filter=Q(estado=Venta.Estado.PENDIENTE)),
            )
            kpis["neto_total"] = q2(kpis["neto_total"])

            pendientes = list(
                Venta.objects.filter(vendedor_id=v.pk, estado=Venta.Estado.PENDIENTE)
                .select_related("comprador")
                .order_by("-creado_en", "-id")[:80]
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

    pendientes_qs = Venta.objects.filter(estado=Venta.Estado.PENDIENTE).select_related(
        "vendedor", "comprador"
    )
    ventas_pendientes_total = pendientes_qs.count()
    pendientes = list(pendientes_qs.order_by("-creado_en", "-id")[:80])

    neto_nonneg = venta_neto_nonneg_expr()
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
            "ventas_pendientes_total": ventas_pendientes_total,
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

    next_url = safe_internal_path(request.GET.get("next") or "")
    idle_timeout = request.GET.get("idle") == "1" or request.POST.get("idle") == "1"

    error = None
    # El checkbox se muestra en el login; si el usuario no puede o no aplica, se ignora.
    vendedor_option_visible = True
    vendedor_option_checked = False
    vendedor_option_locked = False
    if request.method == "POST":
        next_url = safe_internal_path(request.POST.get("next") or "") or next_url
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        ip = client_ip(request)
        block_key = f"login:block:{ip}"
        fail_key = f"login:fail:{ip}"
        if cache.get(block_key):
            error = "Demasiados intentos fallidos. Esperá unos minutos y volvé a intentar."
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                cache.delete(fail_key)
                cache.delete(block_key)
                login(request, user)
                if next_url:
                    return redirect(next_url)
                try:
                    solo_vendedor = bool(
                        getattr(getattr(user, "perfil_acceso", None), "solo_vendedor", False)
                    )
                    entrar = (request.POST.get("entrar_como_vendedor") or "0") == "1"
                    v = _ensure_vendedor_perfil(user) if entrar else _safe_get_vendedor_perfil(user)

                    # Guardar modo en sesión (para menú/layout). Staff puede entrar como vendedor con el checkbox.
                    modo = bool(solo_vendedor or (entrar and v is not None))
                    request.session["modo_vendedor"] = modo

                    if solo_vendedor:
                        if v is None:
                            messages.error(
                                request,
                                "Tu usuario está marcado como 'solo vendedor' pero no tiene perfil de vendedor asignado.",
                            )
                            logout(request)
                            return redirect("login")
                        return redirect("vendedor_home")
                    if entrar and v is not None:
                        return redirect("vendedor_home")
                    if entrar and v is None:
                        messages.error(request, "No se pudo preparar el perfil de vendedor para este usuario.")
                except Exception:
                    pass
                return redirect("home")
            fails = int(cache.get(fail_key, 0) or 0) + 1
            cache.set(fail_key, fails, 900)
            if fails >= 10:
                cache.set(block_key, 1, 600)
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
    v = _ensure_vendedor_perfil(request.user)
    if (solo_vendedor or v is not None) and v is not None:
        request.session["modo_vendedor"] = True
        return redirect("vendedor_home")

    messages.error(request, "No se pudo preparar el perfil de vendedor para este usuario.")
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
@require_http_methods(["GET"])
def switch_to_admin_mode(request):
    """
    Atajo para usuarios staff: salir de modo vendedor (si estaba) y entrar al panel de administración del sistema.
    """
    if not getattr(request.user, "is_staff", False):
        return redirect("home")
    try:
        request.session["modo_vendedor"] = False
        request.session.pop("modo_vendedor", None)
    except Exception:
        pass
    return redirect("admin_usuarios_list")


@login_required
@require_http_methods(["GET", "POST"])
def cambiar_password(request):
    if request.method == "POST":
        form = SironaPasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Tu contraseña fue actualizada.")
            if bool(request.session.get("modo_vendedor", False)):
                return redirect("vendedor_home")
            return redirect("home")
    else:
        form = SironaPasswordChangeForm(user=request.user)

    return render(request, "core/cambiar_password.html", {"form": form})


def _notas_es_ajax(request) -> bool:
    return (request.headers.get("X-Requested-With") or "").strip().lower() == "xmlhttprequest"


@login_required
@require_http_methods(["POST"])
def nota_admin_enviar(request):
    texto = (request.POST.get("nota_texto") or "").strip()
    if not texto:
        if _notas_es_ajax(request):
            return JsonResponse({"ok": False, "error": "Escribí un mensaje antes de enviar."}, status=400)
        messages.error(request, "Escribí una nota antes de enviar.")
        return redirect(safe_internal_path(request.POST.get("next") or "") or "home")

    v = _safe_get_vendedor_perfil(request.user)
    pagina = (request.POST.get("pagina") or "").strip()
    parent = None
    parent_raw = (request.POST.get("parent_id") or "").strip()
    if parent_raw.isdigit():
        parent = (
            NotaAdmin.objects.filter(
                pk=int(parent_raw),
                parent__isnull=True,
                usuario=request.user,
                es_staff=False,
            )
            .select_related("vendedor")
            .first()
        )
        if parent is None:
            if _notas_es_ajax(request):
                return JsonResponse({"ok": False, "error": "Hilo no válido."}, status=400)
            messages.error(request, "No se pudo responder en ese hilo.")
            return redirect(safe_internal_path(request.POST.get("next") or "") or "home")

    nota = NotaAdmin.objects.create(
        usuario=request.user,
        vendedor=parent.vendedor if parent is not None else (v if v is not None else None),
        texto=texto[:2000],
        pagina=pagina[:255] if parent is None else "",
        parent=parent,
        es_staff=False,
        leida=False,
        leida_usuario=True,
        creado_por=None,
    )

    if _notas_es_ajax(request):
        return JsonResponse(
            {
                "ok": True,
                "nueva_raiz_id": nota.pk if parent is None else None,
                "mensaje": {
                    "id": nota.pk,
                    "texto": nota.texto,
                    "creado_en": nota.creado_en.isoformat(),
                    "es_staff": False,
                    "autor": request.user.get_username(),
                },
            }
        )

    messages.success(request, "Nota enviada a administración.")
    return redirect(safe_internal_path(request.POST.get("next") or "") or "home")


@login_required
@require_http_methods(["GET"])
def notas_chat_json(request):
    user = request.user
    roots = list(
        NotaAdmin.objects.filter(usuario=user, parent__isnull=True, es_staff=False)
        .order_by("-creado_en", "-id")
    )
    hilos = []
    for r in roots:
        raw = (r.texto or "").replace("\n", " ").strip()
        preview = (raw[:72] + "…") if len(raw) > 72 else (raw or "(sin texto)")
        no_leidas = NotaAdmin.objects.filter(
            parent=r, es_staff=True, leida_usuario=False
        ).count()
        hilos.append(
            {
                "id": r.pk,
                "preview": preview,
                "creado_en": r.creado_en.isoformat(),
                "no_leidas": no_leidas,
            }
        )

    if (request.GET.get("nuevo") or "").strip() == "1":
        return JsonResponse(
            {
                "hilos": hilos,
                "hilo_id": None,
                "mensajes": [],
                "ultima_raiz_id": roots[0].pk if roots else None,
            }
        )

    hilo_raw = (request.GET.get("hilo") or "").strip()
    hilo_id = None
    if hilo_raw.isdigit():
        cand = next((r.pk for r in roots if r.pk == int(hilo_raw)), None)
        if cand is not None:
            hilo_id = cand
    if hilo_id is None and roots:
        hilo_id = roots[0].pk

    mensajes = []
    if hilo_id is not None:
        msg_qs = (
            NotaAdmin.objects.filter(usuario=user)
            .filter(Q(pk=hilo_id) | Q(parent_id=hilo_id))
            .select_related("creado_por", "usuario")
            .order_by("creado_en", "id")
        )
        for m in msg_qs:
            autor = "Administración"
            if not m.es_staff:
                autor = m.usuario.get_username()
            elif m.creado_por_id:
                autor = m.creado_por.get_username()
            mensajes.append(
                {
                    "id": m.pk,
                    "texto": m.texto,
                    "creado_en": m.creado_en.isoformat(),
                    "es_staff": m.es_staff,
                    "autor": autor,
                    "parent_id": m.parent_id,
                }
            )

    return JsonResponse(
        {
            "hilos": hilos,
            "hilo_id": hilo_id,
            "mensajes": mensajes,
            "ultima_raiz_id": roots[0].pk if roots else None,
        }
    )


@login_required
@require_http_methods(["POST"])
def notas_marcar_leidas_usuario(request):
    if not _notas_es_ajax(request):
        return JsonResponse({"ok": False}, status=400)
    user = request.user
    hilo_raw = (request.POST.get("hilo_id") or "").strip()
    if hilo_raw.isdigit():
        raiz = NotaAdmin.objects.filter(
            pk=int(hilo_raw), usuario=user, parent__isnull=True, es_staff=False
        ).first()
        if raiz is None:
            return JsonResponse({"ok": False, "error": "Hilo no válido."}, status=400)
        NotaAdmin.objects.filter(
            usuario=user,
            parent=raiz,
            es_staff=True,
            leida_usuario=False,
        ).update(leida_usuario=True)
    else:
        NotaAdmin.objects.filter(usuario=user, es_staff=True, leida_usuario=False).update(
            leida_usuario=True
        )
    sin_leer = NotaAdmin.objects.filter(
        usuario=user, es_staff=True, leida_usuario=False
    ).count()
    return JsonResponse({"ok": True, "sin_leer": sin_leer})

