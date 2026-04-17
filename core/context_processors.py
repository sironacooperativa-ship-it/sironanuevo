from __future__ import annotations


def vendor_mode(request):
    """
    Exponer en templates si el usuario está en modo vendedor (portal reducido).
    Se determina por sesión o por flag de acceso del usuario.
    """

    solo_vendedor = bool(
        getattr(getattr(getattr(request, "user", None), "perfil_acceso", None), "solo_vendedor", False)
    )
    session_flag = bool(getattr(getattr(request, "session", None), "get", lambda _k, _d=None: False)("modo_vendedor", False))
    return {"vendor_mode": bool(solo_vendedor or session_flag)}

