from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from io import BytesIO, StringIO
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from django.core.management import call_command
from django.db import connections, transaction
from django.http import FileResponse, HttpResponseBadRequest
from django.utils import timezone
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


def _usa_sqlite() -> bool:
    eng = settings.DATABASES["default"].get("ENGINE", "")
    return "sqlite" in eng.lower()


def _backup_completo_zip() -> tuple[BytesIO, str]:
    """
    ZIP con datos.json (dumpdata) y, si aplica, copia de SQLite.
    """
    buf = BytesIO()
    ts = timezone.now().strftime("%Y%m%d_%H%M%S")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        out = StringIO()
        call_command(
            "dumpdata",
            exclude=["sessions", "admin"],
            stdout=out,
            indent=2,
            use_natural_foreign_keys=True,
            use_natural_primary_keys=True,
        )
        zf.writestr("datos.json", out.getvalue().encode("utf-8"))

        readme_lines = [
            f"BACKUP SIRONA — {timezone.now().isoformat()}",
            "",
            "CONTENIDO",
            "---------",
            "- datos.json: exportación de datos (usuarios, productos, movimientos, etc.).",
            "  No incluye sesiones web ni el registro interno del panel admin de Django.",
            "",
        ]
        sqlite_p = _db_path()
        if _usa_sqlite() and sqlite_p.is_file():
            zf.write(sqlite_p, arcname="sqlite/sirona.sqlite3")
            readme_lines.extend(
                [
                    "- sqlite/sirona.sqlite3: copia del archivo de base SQLite.",
                    "  Restauración rápida local: reemplazar db.sqlite3 por este archivo",
                    "  (con el servidor detenido) o usar «Restaurar» en Administrador.",
                    "",
                ]
            )
        else:
            readme_lines.extend(
                [
                    "- (No hay sqlite/) Esta copia se generó sobre PostgreSQL u otra base.",
                    "  Conservá datos.json para migrar o restaurar en otro entorno (ver tutorial).",
                    "",
                ]
            )
        readme_lines.extend(
            [
                "Restaurar datos.json suele hacerse con el proyecto en local y el comando",
                "documentado en INSTALACION_Y_BACKUP.md (loaddata).",
            ]
        )
        zf.writestr("LEEME_BACKUP.txt", "\n".join(readme_lines))

    buf.seek(0)
    return buf, f"sirona_backup_{ts}.zip"


@admin_required
@require_http_methods(["GET"])
def backup_descargar(request):
    try:
        buf, filename = _backup_completo_zip()
    except Exception as exc:
        return HttpResponseBadRequest(f"No se pudo generar el backup: {exc}")

    return FileResponse(
        buf,
        as_attachment=True,
        filename=filename,
        content_type="application/zip",
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


@admin_required
@require_http_methods(["POST"])
def reset_datos(request):
    """
    Borra datos operativos para empezar de cero (no toca usuarios ni migraciones).
    Requiere confirmación escribiendo RESET.
    """
    texto = (request.POST.get("confirm_text") or "").strip().upper()
    if texto != "RESET":
        messages.error(request, "Escribí RESET para confirmar.")
        return redirect("admin_usuarios_list")

    borrar_productos = (request.POST.get("borrar_productos") or "").strip() == "1"

    # Imports locales para evitar carga innecesaria
    from bancos.models import Gasto, MovimientoCuentaBancaria
    from caja.models import MovimientoCaja
    from calendario.models import Evento
    from compras.models import Compra
    from presupuestos.models import Presupuesto, PresupuestoLinea
    from stock.models import MovimientoStock
    from ventas.models import Venta, VentaLinea
    from productos.models import ListaPrecios, Producto

    with transaction.atomic():
        # Ventas / presupuestos / compras / caja / calendario / stock / bancos
        VentaLinea.objects.all().delete()
        Venta.objects.all().delete()
        PresupuestoLinea.objects.all().delete()
        Presupuesto.objects.all().delete()

        Compra.objects.all().delete()
        MovimientoStock.objects.all().delete()
        Evento.objects.all().delete()

        Gasto.objects.all().delete()
        MovimientoCuentaBancaria.objects.all().delete()
        MovimientoCaja.objects.all().delete()

        # Productos (opcional)
        if borrar_productos:
            # Limpiar listas primero
            ListaPrecios.objects.all().delete()
            Producto.objects.all().delete()
        else:
            # Dejar productos pero resetear stock y flags típicos de pruebas
            Producto.objects.all().update(stock=0, en_lista_precios=False)
            ListaPrecios.objects.all().delete()

    messages.success(
        request,
        "Sistema reseteado. Se borraron movimientos/ventas/compras/presupuestos/caja/calendario. "
        + ("También se borraron productos." if borrar_productos else "Se mantuvieron productos (stock en 0)."),
    )
    return redirect("admin_usuarios_list")

