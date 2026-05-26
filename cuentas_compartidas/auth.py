from django.contrib.auth.decorators import login_required, permission_required


PERMISO_CUENTAS_COMPARTIDAS = "cuentas_compartidas.access_cuentas_compartidas"


def puede_usar_cuentas_compartidas(user) -> bool:
    return bool(user and user.is_authenticated and user.has_perm(PERMISO_CUENTAS_COMPARTIDAS))


def cuentas_compartidas_required(view):
    return login_required(permission_required(PERMISO_CUENTAS_COMPARTIDAS, raise_exception=True)(view))
