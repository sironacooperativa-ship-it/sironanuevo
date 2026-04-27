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
    vendedor_perfil_pk = None
    notas_admin_no_leidas = 0
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            v = user.vendedor_perfil
            if isinstance(v, Vendedor):
                has_vendedor_perfil = True
                vendedor_perfil_pk = v.pk
        except ObjectDoesNotExist:
            has_vendedor_perfil = False
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            notas_admin_no_leidas = NotaAdmin.objects.filter(leida=False).count()

    return {
        "vendor_mode": bool(solo_vendedor or session_flag or in_portal),
        "has_vendedor_perfil": has_vendedor_perfil,
        "vendedor_perfil_pk": vendedor_perfil_pk,
        "notas_admin_no_leidas": notas_admin_no_leidas,
    }

