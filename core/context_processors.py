from __future__ import annotations

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
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            v = user.vendedor_perfil
            has_vendedor_perfil = isinstance(v, Vendedor)
        except Exception:
            has_vendedor_perfil = False

    return {
        "vendor_mode": bool(solo_vendedor or session_flag or in_portal),
        "has_vendedor_perfil": has_vendedor_perfil,
    }

