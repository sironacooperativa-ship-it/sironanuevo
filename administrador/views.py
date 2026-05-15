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
from django.core.paginator import Paginator
from django.db import connections, transaction
from django.db.models import Exists, OuterRef, Q
from django.http import FileResponse, HttpResponseBadRequest
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.fecha_filtros import fecha_filtro_value_iso, parse_fecha_param
from core.context_processors import invalidate_vendor_sidebar_cache_for_user
from core.models import NotaAdmin

from .forms import UsuarioCrearForm, UsuarioEditarForm, UsuarioPasswordForm
from .models import RegistroActividad


User = get_user_model()


def _es_admin(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def _recibe_notas_admin(user) -> bool:
    return bool(user and user.is_authenticated and user.is_staff)


def admin_required(view):
    return login_required(user_passes_test(_es_admin)(view))


def notas_admin_required(view):
    return login_required(user_passes_test(_recibe_notas_admin)(view))


@admin_required
def actividad_list(request):
    qs = RegistroActividad.objects.select_related("usuario").all()
    uid = (request.GET.get("usuario") or "").strip()
    if uid.isdigit():
        qs = qs.filter(usuario_id=int(uid))
    desde = parse_fecha_param(request.GET.get("desde") or "")
    hasta = parse_fecha_param(request.GET.get("hasta") or "")
    if desde:
        qs = qs.filter(fecha_hora__date__gte=desde)
    if hasta:
        qs = qs.filter(fecha_hora__date__lte=hasta)
    qpath = (request.GET.get("q") or "").strip()
    if qpath:
        qs = qs.filter(ruta__icontains=qpath)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page") or 1)
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    querystring = qcopy.urlencode()
    return render(
        request,
        "administrador/actividad_list.html",
        {
            "page_obj": page,
            "usuarios_filtro": User.objects.order_by("username"),
            "filtros": {
                "usuario": uid,
                "desde": fecha_filtro_value_iso(request.GET.get("desde")),
                "hasta": fecha_filtro_value_iso(request.GET.get("hasta")),
                "q": qpath,
            },
            "querystring": querystring,
        },
    )


@admin_required
def usuarios_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = User.objects.order_by("username")
    if q:
        qs = qs.filter(username__icontains=q) | qs.filter(email__icontains=q)
        qs = qs.distinct().order_by("username")
    return render(request, "administrador/usuarios_list.html", {"usuarios": qs, "q": q})


@notas_admin_required
@require_http_methods(["GET", "POST"])
def notas_list(request):
    if request.method == "POST":
        accion = (request.POST.get("accion") or "").strip()
        if accion == "responder":
            root_id = (request.POST.get("root_id") or "").strip()
            texto_resp = (request.POST.get("texto_respuesta") or "").strip()
            if not root_id.isdigit() or not texto_resp:
                messages.error(request, "Completá el mensaje de respuesta.")
                return redirect("admin_notas_list")
            root = get_object_or_404(NotaAdmin, pk=int(root_id), parent__isnull=True)
            NotaAdmin.objects.create(
                usuario=root.usuario,
                vendedor=root.vendedor,
                texto=texto_resp[:2000],
                pagina="",
                parent=root,
                es_staff=True,
                leida=True,
                leida_usuario=False,
                creado_por=request.user,
            )
            messages.success(request, "Respuesta enviada.")
            invalidate_vendor_sidebar_cache_for_user(root.usuario)
            return redirect("admin_notas_list")

        nota_id = (request.POST.get("nota_id") or "").strip()
        if not nota_id.isdigit():
            messages.error(request, "Nota no válida.")
            return redirect("admin_notas_list")

        nota = get_object_or_404(NotaAdmin, pk=int(nota_id))
        if accion == "marcar_leida":
            nota.leida = True
            nota.save(update_fields=["leida"])
            if nota.parent_id is None:
                NotaAdmin.objects.filter(parent=nota, es_staff=False).update(leida=True)
            messages.success(request, "Nota marcada como leída.")
        elif accion == "marcar_no_leida":
            nota.leida = False
            nota.save(update_fields=["leida"])
            if nota.parent_id is None:
                NotaAdmin.objects.filter(parent=nota, es_staff=False).update(leida=False)
            messages.success(request, "Nota marcada como no leída.")
        elif accion == "eliminar":
            nota.delete()
            messages.success(request, "Nota eliminada.")
        else:
            messages.error(request, "Acción no válida.")
        return redirect("admin_notas_list")

    estado = (request.GET.get("estado") or "no_leidas").strip()
    q = (request.GET.get("q") or "").strip()

    unread_child = NotaAdmin.objects.filter(
        parent_id=OuterRef("pk"),
        es_staff=False,
        leida=False,
    )
    qs = (
        NotaAdmin.objects.filter(parent__isnull=True)
        .select_related("usuario", "vendedor")
        .annotate(unread_child=Exists(unread_child))
    )
    if estado == "no_leidas":
        qs = qs.filter(Q(leida=False) | Q(unread_child=True))
    elif estado == "leidas":
        qs = qs.filter(leida=True, unread_child=False)
    else:
        estado = "todas"

    if q:
        reply_match = NotaAdmin.objects.filter(
            parent__isnull=False,
        ).filter(
            Q(texto__icontains=q)
            | Q(usuario__username__icontains=q)
            | Q(usuario__email__icontains=q)
        ).values_list("parent_id", flat=True)
        qs = qs.filter(
            Q(texto__icontains=q)
            | Q(usuario__username__icontains=q)
            | Q(usuario__email__icontains=q)
            | Q(vendedor__codigo__icontains=q)
            | Q(vendedor__apellido__icontains=q)
            | Q(pk__in=reply_match)
        ).distinct()

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page") or 1)

    root_ids = [r.pk for r in page.object_list]
    hilos_por_raiz: dict[int, list[NotaAdmin]] = {}
    if root_ids:
        for m in (
            NotaAdmin.objects.filter(Q(pk__in=root_ids) | Q(parent_id__in=root_ids))
            .select_related("usuario", "vendedor", "creado_por")
            .order_by("creado_en", "id")
        ):
            rid = m.parent_id or m.pk
            hilos_por_raiz.setdefault(rid, []).append(m)
    for r in page.object_list:
        r.hilo_mensajes = hilos_por_raiz.get(r.pk, [r])

    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    return render(
        request,
        "administrador/notas_list.html",
        {
            "page_obj": page,
            "filtros": {"estado": estado, "q": q},
            "querystring": qcopy.urlencode(),
            "total_no_leidas": NotaAdmin.objects.filter(es_staff=False, leida=False).count(),
        },
    )


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


def _dangerous_admin_actions_enabled() -> bool:
    """
    Permite bloquear acciones destructivas en producción.
    Default: habilitado solo en DEBUG, o si se setea explícitamente el flag.
    """
    if bool(getattr(settings, "DEBUG", False)):
        return True
    return str(os.environ.get("SIRONA_ENABLE_DANGEROUS_ADMIN_ACTIONS", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _is_sqlite_file_header(raw16: bytes) -> bool:
    return bool(raw16 and raw16.startswith(b"SQLite format 3\x00"))


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
    if not getattr(request.user, "is_superuser", False):
        messages.error(request, "Solo un superusuario puede descargar backups.")
        return redirect("admin_usuarios_list")

    if not _dangerous_admin_actions_enabled():
        messages.error(request, "Descargar backup está deshabilitado en este entorno.")
        return redirect("admin_usuarios_list")

    try:
        buf, filename = _backup_completo_zip()
    except Exception as exc:
        detalle = f" Detalle: {exc}" if getattr(request.user, "is_staff", False) else ""
        return HttpResponseBadRequest("No se pudo generar el backup." + detalle)

    return FileResponse(
        buf,
        as_attachment=True,
        filename=filename,
        content_type="application/zip",
    )


@admin_required
@require_http_methods(["POST"])
def backup_restaurar(request):
    if not getattr(request.user, "is_superuser", False):
        messages.error(request, "Solo un superusuario puede restaurar un backup.")
        return redirect("admin_usuarios_list")

    if not _dangerous_admin_actions_enabled():
        messages.error(request, "Restaurar backup está deshabilitado en este entorno.")
        return redirect("admin_usuarios_list")

    if not _usa_sqlite():
        messages.error(request, "Este servidor no usa SQLite, no se puede restaurar un archivo .sqlite3 acá.")
        return redirect("admin_usuarios_list")

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

    max_mb = int(os.environ.get("SIRONA_MAX_SQLITE_UPLOAD_MB", "200"))
    if getattr(f, "size", 0) and f.size > (max_mb * 1024 * 1024):
        messages.error(request, f"El archivo es demasiado grande (máx. {max_mb} MB).")
        return redirect("admin_usuarios_list")

    dest = _db_path()
    if not dest.exists():
        messages.error(request, "No se encontró la base de datos actual.")
        return redirect("admin_usuarios_list")

    # Guardar en temporal y reemplazar de forma atómica.
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        # Chequear cabecera SQLite.
        try:
            header = f.read(16)
        except Exception:
            header = b""
        if not _is_sqlite_file_header(header):
            messages.error(request, "El archivo no parece ser una base SQLite válida.")
            try:
                f.seek(0)
            except Exception:
                pass
            return redirect("admin_usuarios_list")
        try:
            f.seek(0)
        except Exception:
            pass

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
    if not getattr(request.user, "is_superuser", False):
        messages.error(request, "Solo un superusuario puede resetear datos.")
        return redirect("admin_usuarios_list")

    if not _dangerous_admin_actions_enabled():
        messages.error(request, "Resetear datos está deshabilitado en este entorno.")
        return redirect("admin_usuarios_list")

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
            Producto.objects.all().update(stock=0, en_lista_precios=False, habilitado=False)
            ListaPrecios.objects.all().delete()

    messages.success(
        request,
        "Sistema reseteado. Se borraron movimientos/ventas/compras/presupuestos/caja/calendario. "
        + ("También se borraron productos." if borrar_productos else "Se mantuvieron productos (stock en 0)."),
    )
    return redirect("admin_usuarios_list")

