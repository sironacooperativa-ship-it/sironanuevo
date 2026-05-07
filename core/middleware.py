"""Middleware de acceso por rol."""
from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url

from core.models import PerfilAcceso


class VendedorAccessMiddleware:
    """
    Enforce acceso por usuario:
    - usuario.perfil_acceso.solo_vendedor=True: siempre portal (bloquea sistema completo)
    - caso contrario: acceso completo (y si entra al portal es por elección en login)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not getattr(request.user, "is_staff", False):
            path = request.path or "/"
            if (
                path.startswith("/static/")
                or path.startswith("/login/")
                or path.startswith("/logout/")
                or path.startswith("/admin/")
                or path.startswith("/health/")
                or path.startswith("/warmup/")
            ):
                return self.get_response(request)

            # Si no existe el perfil aún (usuarios viejos), lo creamos.
            perfil = getattr(request.user, "perfil_acceso", None)
            if perfil is None:
                try:
                    tiene_vendedor = request.user.vendedor_perfil is not None
                except ObjectDoesNotExist:
                    tiene_vendedor = False
                PerfilAcceso.objects.get_or_create(
                    usuario=request.user,
                    defaults={"solo_vendedor": bool(tiene_vendedor)},
                )
                perfil = getattr(request.user, "perfil_acceso", None)

            solo_vendedor = bool(getattr(perfil, "solo_vendedor", False))
            in_portal = path.startswith("/vendedor/")
            # Enlace firmado de presupuesto (cliente): no forzar portal
            presupuesto_compartido = path.startswith("/presupuestos/c/")
            if solo_vendedor and not in_portal and not presupuesto_compartido:
                request.session["modo_vendedor"] = True
                return HttpResponseRedirect(resolve_url("vendedor_home"))

        return self.get_response(request)
