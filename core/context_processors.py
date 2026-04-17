from __future__ import annotations


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
    return {"vendor_mode": bool(solo_vendedor or session_flag or in_portal)}

