from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist

from core.models import NotaAdmin
from personas.models import Vendedor


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
    notas_admin_no_leidas = 0
    notas_usuario_no_leidas = 0
    recibe_notas_admin = False
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            v = user.vendedor_perfil
            if isinstance(v, Vendedor):
                has_vendedor_perfil = True
                vendedor_perfil_pk = v.pk
        except ObjectDoesNotExist:
            has_vendedor_perfil = False
        can_switch_to_vendor_mode = bool(not solo_vendedor)
        recibe_notas_admin = bool(
            getattr(user, "is_superuser", False)
            or (getattr(user, "username", "") or "").strip().lower() == "admin"
        )
        if recibe_notas_admin:
            notas_admin_no_leidas = NotaAdmin.objects.filter(es_staff=False, leida=False).count()
        else:
            notas_usuario_no_leidas = NotaAdmin.objects.filter(
                usuario=user, es_staff=True, leida_usuario=False
            ).count()

    pa = getattr(user, "perfil_acceso", None) if user is not None and getattr(user, "is_authenticated", False) else None
    solo_vendedor_profile = bool(getattr(pa, "solo_vendedor", False)) if pa is not None else False
    if user is not None and getattr(user, "is_authenticated", False):
        can_switch_to_full_mode = bool(
            has_vendedor_perfil and (pa is None or not solo_vendedor_profile)
        )

    return {
        "vendor_mode": bool(solo_vendedor or session_flag or in_portal),
        "has_vendedor_perfil": has_vendedor_perfil,
        "can_switch_to_vendor_mode": can_switch_to_vendor_mode,
        "can_switch_to_full_mode": can_switch_to_full_mode,
        "vendedor_perfil_pk": vendedor_perfil_pk,
        "notas_admin_no_leidas": notas_admin_no_leidas,
        "notas_usuario_no_leidas": notas_usuario_no_leidas,
        "recibe_notas_admin": recibe_notas_admin,
    }

