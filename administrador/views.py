from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from django.db import connections
from django.http import FileResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import UsuarioCrearForm, UsuarioEditarForm, UsuarioPasswordForm


User = get_user_model()


def _es_admin(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def admin_required(view):
    return login_required(user_passes_test(_es_admin)(view))


@admin_required
def usuarios_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = User.objects.order_by("username")
    if q:
        qs = qs.filter(username__icontains=q) | qs.filter(email__icontains=q)
        qs = qs.distinct().order_by("username")
    return render(request, "administrador/usuarios_list.html", {"usuarios": qs, "q": q})


@admin_required
@require_http_methods(["GET", "POST"])
def usuario_create(request):
    if request.method == "POST":
        form = UsuarioCrearForm(request.POST)
        if form.is_valid():
            u = form.save()
            messages.success(request, f"Usuario {u.username} creado.")
            return redirect("admin_usuarios_list")
    else:
        form = UsuarioCrearForm(initial={"is_active": True, "is_staff": False})
    return render(request, "administrador/usuario_form.html", {"form": form, "modo": "nuevo"})


@admin_required
@require_http_methods(["GET", "POST"])
def usuario_update(request, pk: int):
    u = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UsuarioEditarForm(request.POST, instance=u)
        if form.is_valid():
            form.save()
            messages.success(request, "Usuario actualizado.")
            return redirect("admin_usuarios_list")
    else:
        form = UsuarioEditarForm(instance=u)
    return render(
        request,
        "administrador/usuario_form.html",
        {"form": form, "modo": "editar", "usuario": u},
    )


@admin_required
@require_http_methods(["GET", "POST"])
def usuario_password(request, pk: int):
    u = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UsuarioPasswordForm(request.POST)
        if form.is_valid():
            u.set_password(form.cleaned_data["password1"])
            u.save(update_fields=["password"])
            messages.success(request, "Contraseña actualizada.")
            return redirect("admin_usuarios_list")
    else:
        form = UsuarioPasswordForm()
    return render(
        request,
        "administrador/usuario_password.html",
        {"form": form, "usuario": u},
    )


def _db_path() -> Path:
    # Proyecto usa SQLite por defecto.
    return Path(settings.BASE_DIR) / "db.sqlite3"


@admin_required
@require_http_methods(["GET"])
def backup_descargar(request):
    p = _db_path()
    if not p.exists():
        return HttpResponseBadRequest("No se encontró la base de datos.")
    return FileResponse(
        open(p, "rb"),
        as_attachment=True,
        filename="backup_sirona.sqlite3",
        content_type="application/x-sqlite3",
    )


@admin_required
@require_http_methods(["POST"])
def backup_restaurar(request):
    confirm = (request.POST.get("confirm") or "").strip()
    if confirm != "1":
        messages.error(request, "Marcá la confirmación para restaurar el backup.")
        return redirect("admin_usuarios_list")

    f = request.FILES.get("archivo")
    if not f:
        messages.error(request, "Seleccioná un archivo de backup (.sqlite3).")
        return redirect("admin_usuarios_list")

    name = (getattr(f, "name", "") or "").lower()
    if not (name.endswith(".sqlite3") or name.endswith(".db") or name.endswith(".sqlite")):
        messages.error(request, "Formato no válido. Subí un archivo .sqlite3/.db/.sqlite")
        return redirect("admin_usuarios_list")

    dest = _db_path()
    if not dest.exists():
        messages.error(request, "No se encontró la base de datos actual.")
        return redirect("admin_usuarios_list")

    # Guardar en temporal y reemplazar de forma atómica.
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        for chunk in f.chunks():
            tmp.write(chunk)
        tmp_path = Path(tmp.name)

    try:
        connections.close_all()
        backup_old = dest.with_name("db.before_restore.sqlite3")
        shutil.copy2(dest, backup_old)
        os.replace(tmp_path, dest)
    except Exception as exc:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        messages.error(request, f"No se pudo restaurar el backup: {exc}")
        return redirect("admin_usuarios_list")

    messages.success(
        request,
        "Backup restaurado. Se guardó una copia previa como db.before_restore.sqlite3. "
        "Si tenés el servidor levantado, reinicialo para tomar la base nueva.",
    )
    return redirect("admin_usuarios_list")

