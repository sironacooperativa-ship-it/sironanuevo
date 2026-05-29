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
from django.http import FileResponse, HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

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


def _nota_raiz_usuario(usuario):
    return (
        NotaAdmin.objects.filter(usuario=usuario, parent__isnull=True, es_staff=False)
        .order_by("creado_en", "id")
        .first()
    )


def _autor_mensaje_nota(m: NotaAdmin) -> str:
    if not m.es_staff:
        return m.usuario.get_username()
    if m.creado_por_id:
        return m.creado_por.get_username()
    return "Administración"


def _mensaje_nota_dict(m: NotaAdmin) -> dict:
    return {
        "id": m.pk,
        "texto": m.texto,
        "creado_en": m.creado_en.isoformat(),
        "es_staff": m.es_staff,
        "autor": _autor_mensaje_nota(m),
        "leida": m.leida,
        "resuelto": bool(m.resuelto) if not m.es_staff else None,
    }


def _conversaciones_admin(*, usuarios: list, marcar_leidos: bool) -> list[dict]:
    conversaciones = []
    for usuario in usuarios:
        mensajes = list(
            NotaAdmin.objects.filter(usuario=usuario)
            .select_related("usuario", "vendedor", "creado_por")
            .order_by("-creado_en", "-id")
        )
        ultimo_en = mensajes[0].creado_en if mensajes else None
        conversaciones.append(
            {
                "usuario": usuario,
                "mensajes": mensajes,
                "mensajes_json": [_mensaje_nota_dict(m) for m in mensajes],
                "no_leidos": sum(1 for m in mensajes if not m.es_staff and not m.leida),
                "pendientes": sum(1 for m in mensajes if not m.es_staff and not m.resuelto),
                "_ultimo_en": ultimo_en,
            }
        )
    conversaciones.sort(
        key=lambda c: c["_ultimo_en"].timestamp() if c["_ultimo_en"] else 0,
        reverse=True,
    )
    for c in conversaciones:
        c.pop("_ultimo_en", None)
    if marcar_leidos:
        NotaAdmin.objects.filter(es_staff=False, leida=False).update(leida=True)
    return conversaciones


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
        usuario_id = (request.POST.get("usuario_id") or "").strip()
        texto_resp = (request.POST.get("texto_respuesta") or "").strip()
        if not usuario_id.isdigit() or not texto_resp:
            messages.error(request, "Completá el mensaje de respuesta.")
            return redirect("admin_notas_list")
        usuario = get_object_or_404(User, pk=int(usuario_id))
        root = (
            NotaAdmin.objects.filter(usuario=usuario, parent__isnull=True, es_staff=False)
            .order_by("creado_en", "id")
            .first()
        )
        if root is None:
            if (request.headers.get("X-Requested-With") or "").strip().lower() == "xmlhttprequest":
                return JsonResponse({"ok": False, "error": "No se encontró la conversación."}, status=400)
            messages.error(request, "No se encontró la conversación.")
            return redirect("admin_notas_list")
        NotaAdmin.objects.create(
            usuario=usuario,
            vendedor=root.vendedor if root else None,
            texto=texto_resp[:2000],
            pagina="",
            parent=root,
            es_staff=True,
            leida=True,
            leida_usuario=False,
            creado_por=request.user,
        )
        messages.success(request, "Respuesta enviada.")
        invalidate_vendor_sidebar_cache_for_user(usuario)
        if (request.headers.get("X-Requested-With") or "").strip().lower() == "xmlhttprequest":
            return JsonResponse({"ok": True})
        return redirect("admin_notas_list")

    q = (request.GET.get("q") or "").strip()
    usuarios_ids = list(NotaAdmin.objects.values_list("usuario_id", flat=True).distinct())
    usuarios = list(User.objects.filter(pk__in=usuarios_ids).order_by("username"))
    if q:
        usuarios = [
            u for u in usuarios
            if q.lower() in u.username.lower()
            or q.lower() in (u.email or "").lower()
            or NotaAdmin.objects.filter(usuario=u, texto__icontains=q).exists()
        ]

    conversaciones = _conversaciones_admin(usuarios=usuarios, marcar_leidos=True)
    total_no_leidas = NotaAdmin.objects.filter(es_staff=False, leida=False).count()
    return render(
        request,
        "administrador/notas_list.html",
        {
            "conversaciones": conversaciones,
            "filtros": {"q": q},
            "total_no_leidas": total_no_leidas,
        },
    )


@notas_admin_required
@require_http_methods(["GET"])
def notas_admin_chat_json(request):
    usuarios_ids = list(NotaAdmin.objects.values_list("usuario_id", flat=True).distinct())
    usuarios = list(User.objects.filter(pk__in=usuarios_ids).order_by("username"))
    conversaciones_raw = _conversaciones_admin(usuarios=usuarios, marcar_leidos=True)
    conversaciones = [
        {
            "usuario_id": c["usuario"].pk,
            "username": c["usuario"].username,
            "email": c["usuario"].email,
            "no_leidos": c["no_leidos"],
            "pendientes": c["pendientes"],
            "mensajes": c["mensajes_json"],
        }
        for c in conversaciones_raw
    ]
    return JsonResponse({"conversaciones": conversaciones, "sin_leer": 0})


@notas_admin_required
@require_POST
def notas_admin_resuelto(request):
    mensaje_id = (request.POST.get("mensaje_id") or "").strip()
    if not mensaje_id.isdigit():
        return JsonResponse({"ok": False, "error": "Mensaje inválido."}, status=400)
    mensaje = get_object_or_404(NotaAdmin, pk=int(mensaje_id), es_staff=False)
    resuelto = (request.POST.get("resuelto") or "").strip().lower() in ("1", "true", "on", "yes")
    if mensaje.resuelto != resuelto:
        mensaje.resuelto = resuelto
        mensaje.save(update_fields=["resuelto"])
    pendientes = NotaAdmin.objects.filter(
        usuario_id=mensaje.usuario_id, es_staff=False, resuelto=False
    ).count()
    return JsonResponse(
        {
            "ok": True,
            "mensaje_id": mensaje.pk,
            "resuelto": mensaje.resuelto,
            "pendientes": pendientes,
        }
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

