from __future__ import annotations

import os

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Exists, F, OuterRef, Q

from core.models import NotaAdmin
from personas.models import Vendedor
from presupuestos.models import Presupuesto, PresupuestoLinea

# Conteos del layout (badges): TTL corto en memoria (por proceso en Render).
_VENDOR_CTX_CACHE_TTL = int(os.environ.get("SIRONA_VENDOR_CONTEXT_CACHE_SECONDS", "20"))
_NOTAS_ADMIN_CACHE_KEY = "sirona:notas_admin_nl:v1"


def _user_recibe_notas_admin(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False) and getattr(user, "is_staff", False))


def _presupuestos_alerta_count(*, vendedor_perfil, limitar_alerta_a_mi_vendedor: bool) -> int:
    try:
        base_qs = Presupuesto.objects.filter(estado=Presupuesto.Estado.ACTIVO)
        if limitar_alerta_a_mi_vendedor:
            if isinstance(vendedor_perfil, Vendedor):
                base_qs = base_qs.filter(vendedor_id=vendedor_perfil.pk)
            else:
                base_qs = base_qs.none()
        alerta_linea = (
            PresupuestoLinea.objects.filter(presupuesto_id=OuterRef("pk"))
            .exclude(precio_unitario=F("producto__precio_venta"))
            .filter(
                Q(precio_catalogo_capturado__isnull=True)
                | ~Q(precio_catalogo_capturado=F("producto__precio_venta"))
            )
        )
        return int(
            base_qs.annotate(tiene_alerta_precio=Exists(alerta_linea))
            .filter(tiene_alerta_precio=True)
            .count()
        )
    except Exception:
        return 0


def invalidate_vendor_sidebar_cache_for_user(user) -> None:
    """
    Limpia conteos cacheados del layout para este usuario (tras enviar/marcar notas, etc.).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return
    cache.delete(_NOTAS_ADMIN_CACHE_KEY)
    if _VENDOR_CTX_CACHE_TTL <= 0:
        return
    if _user_recibe_notas_admin(user):
        return
    vp_ids = {0}
    try:
        v = user.vendedor_perfil
        if isinstance(v, Vendedor):
            vp_ids.add(int(v.pk))
    except ObjectDoesNotExist:
        pass
    is_st = int(getattr(user, "is_staff", False))
    for lim in (0, 1):
        for vp in vp_ids:
            cache.delete(f"sirona:vendor_cc:v1:{user.pk}:{is_st}:{lim}:{vp}")


def vendor_mode(request):
    """
    Exponer en templates si el usuario está en modo vendedor (portal reducido).
    Se determina por sesión o por flag de acceso del usuario.
    """

    solo_vendedor = bool(
        getattr(
            getattr(getattr(request, "user", None), "perfil_acceso", None),
            "solo_vendedor",
            False,
        )
    )
    session_get = getattr(getattr(request, "session", None), "get", None)
    session_flag = bool(session_get("modo_vendedor", False)) if callable(session_get) else False
    path = str(getattr(request, "path", "") or "")
    in_portal = path.startswith("/vendedor/")
    has_vendedor_perfil = False
    can_switch_to_vendor_mode = False
    can_switch_to_full_mode = False
    vendedor_perfil_pk = None
    vendedor_perfil = None
    notas_admin_no_leidas = 0
    notas_usuario_no_leidas = 0
    presupuestos_alerta_count = 0
    recibe_notas_admin = False
    can_switch_admin_mode = False
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            v = user.vendedor_perfil
            if isinstance(v, Vendedor):
                has_vendedor_perfil = True
                vendedor_perfil_pk = v.pk
                vendedor_perfil = v
        except ObjectDoesNotExist:
            has_vendedor_perfil = False
        can_switch_to_vendor_mode = bool(not solo_vendedor)
        can_switch_admin_mode = bool(
            getattr(user, "is_staff", False)
            and isinstance(vendedor_perfil, Vendedor)
            and vendedor_perfil.codigo == "VE0007"
        )
        recibe_notas_admin = _user_recibe_notas_admin(user)
        is_staff = getattr(user, "is_staff", False)
        limitar_alerta_a_mi_vendedor = False
        if not is_staff:
            limitar_alerta_a_mi_vendedor = True
        elif vendedor_perfil is not None and (solo_vendedor or session_flag or in_portal):
            limitar_alerta_a_mi_vendedor = True
        vp_pk = int(vendedor_perfil.pk) if isinstance(vendedor_perfil, Vendedor) else 0

        if recibe_notas_admin:
            cached_notas = cache.get(_NOTAS_ADMIN_CACHE_KEY) if _VENDOR_CTX_CACHE_TTL > 0 else None
            if cached_notas is not None:
                notas_admin_no_leidas = cached_notas
            else:
                notas_admin_no_leidas = NotaAdmin.objects.filter(es_staff=False, leida=False).count()
                if _VENDOR_CTX_CACHE_TTL > 0:
                    cache.set(_NOTAS_ADMIN_CACHE_KEY, notas_admin_no_leidas, _VENDOR_CTX_CACHE_TTL)
            presu_cache_key = (
                f"sirona:presu_alert:v1:{int(is_staff)}:"
                f"{int(limitar_alerta_a_mi_vendedor)}:{vp_pk}"
            )
            cached_presu = cache.get(presu_cache_key) if _VENDOR_CTX_CACHE_TTL > 0 else None
            if cached_presu is not None:
                presupuestos_alerta_count = cached_presu
            else:
                presupuestos_alerta_count = _presupuestos_alerta_count(
                    vendedor_perfil=vendedor_perfil,
                    limitar_alerta_a_mi_vendedor=limitar_alerta_a_mi_vendedor,
                )
                if _VENDOR_CTX_CACHE_TTL > 0:
                    cache.set(presu_cache_key, presupuestos_alerta_count, _VENDOR_CTX_CACHE_TTL)
        else:
            counts_cache_key = (
                f"sirona:vendor_cc:v1:{user.pk}:{int(is_staff)}:"
                f"{int(limitar_alerta_a_mi_vendedor)}:{vp_pk}"
            )
            cached_pair = cache.get(counts_cache_key) if _VENDOR_CTX_CACHE_TTL > 0 else None
            if cached_pair is not None:
                notas_usuario_no_leidas, presupuestos_alerta_count = cached_pair
            else:
                notas_usuario_no_leidas = NotaAdmin.objects.filter(
                    usuario=user, es_staff=True, leida_usuario=False
                ).count()
                presupuestos_alerta_count = _presupuestos_alerta_count(
                    vendedor_perfil=vendedor_perfil,
                    limitar_alerta_a_mi_vendedor=limitar_alerta_a_mi_vendedor,
                )
                if _VENDOR_CTX_CACHE_TTL > 0:
                    cache.set(
                        counts_cache_key,
                        (notas_usuario_no_leidas, presupuestos_alerta_count),
                        _VENDOR_CTX_CACHE_TTL,
                    )

    pa = getattr(user, "perfil_acceso", None) if user is not None and getattr(user, "is_authenticated", False) else None
    solo_vendedor_profile = bool(getattr(pa, "solo_vendedor", False)) if pa is not None else False
    if user is not None and getattr(user, "is_authenticated", False):
        can_switch_to_full_mode = bool(
            has_vendedor_perfil and (pa is None or not solo_vendedor_profile)
        )

    return {
        "vendor_mode": bool(solo_vendedor or session_flag or in_portal),
        "admin_mode": bool(session_get("modo_admin", False)) if callable(session_get) else False,
        "has_vendedor_perfil": has_vendedor_perfil,
        "can_switch_to_vendor_mode": can_switch_to_vendor_mode,
        "can_switch_to_full_mode": can_switch_to_full_mode,
        "can_switch_admin_mode": can_switch_admin_mode,
        "vendedor_perfil_pk": vendedor_perfil_pk,
        "notas_admin_no_leidas": notas_admin_no_leidas,
        "notas_usuario_no_leidas": notas_usuario_no_leidas,
        "recibe_notas_admin": recibe_notas_admin,
        "presupuestos_alerta_count": presupuestos_alerta_count,
        "presupuestos_alerta": presupuestos_alerta_count > 0,
        "logout_on_tab_close_enabled": bool(getattr(settings, "SIRONA_LOGOUT_ON_TAB_CLOSE", False)),
    }


def stock_cero_prompt(request):
    """Productos que quedaron sin stock y esperan decisión vigente/deshabilitar (modal global)."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {"stock_cero_prompt_productos": []}
    try:
        from productos.stock_cero import consumir_prompt_stock_cero

        return {"stock_cero_prompt_productos": consumir_prompt_stock_cero(request)}
    except Exception:
        return {"stock_cero_prompt_productos": []}
