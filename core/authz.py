from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test


def is_staff_user(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def staff_required(view):
    """
    Requiere usuario autenticado con permisos de staff/superuser.
    Útil para acciones que modifican datos globales (personas, borrados, toggles, etc.).
    """

    return login_required(user_passes_test(is_staff_user)(view))

