from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied


PERMISO_CUENTAS_COMPARTIDAS = "cuentas_compartidas.access_cuentas_compartidas"


def puede_usar_cuentas_compartidas(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "is_staff", False)
        and user.has_perm(PERMISO_CUENTAS_COMPARTIDAS)
    )


def es_admin_gastos_compartidos(request) -> bool:
    """Gestión completa del módulo: staff con permiso de Gastos compartidos."""
    user = getattr(request, "user", None)
    return puede_usar_cuentas_compartidas(user)


def cuentas_compartidas_required(view):
    return login_required(permission_required(PERMISO_CUENTAS_COMPARTIDAS, raise_exception=True)(view))


def modo_admin_gastos_required(view):
    @cuentas_compartidas_required
    def _wrapped(request, *args, **kwargs):
        if not es_admin_gastos_compartidos(request):
            raise PermissionDenied("No tenés permiso para administrar Gastos compartidos.")
        return view(request, *args, **kwargs)

    return _wrapped
