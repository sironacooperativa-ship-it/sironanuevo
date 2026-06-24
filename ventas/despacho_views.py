"""Vistas de despachos: armado colectivo y puntos de stock."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_http_methods

from core.authz import staff_required

from .armado_colectivo_pdf import armado_colectivo_pdf_response
from .armado_servicios import (
    actualizar_armado_colectivo,
    agregar_lineas_armado_colectivo,
    armado_edit_id_desde_sesion,
    armados_colectivos_guardados_lista,
    asignaciones_desde_armado_guardado,
    guardar_armado_colectivo,
    lineas_armado_colectivo_desde_guardado,
    lineas_con_celdas_alloc,
    lineas_desde_armado_guardado,
    normalizar_ids_sesion,
    parse_asignaciones_post,
    preparar_edicion_armado,
    puntos_stock_armado_lista,
    tomar_preselect_ids,
    validar_asignaciones,
    venta_ids_reservados_para_lista,
    ventas_no_armadas_queryset,
    ventas_validas_para_armado_colectivo,
    SESSION_ARMADO_EDIT_ID,
    SESSION_ARMADO_PREFILL,
    SESSION_ARMADO_PRESELECT,
)
from .models import ArmadoColectivoGuardado, PuntoStockArmado, Venta

from .despacho_servicios import marcar_pedidos_armados, marcar_pedidos_despachados

SESSION_ARMADO_VENTAS = "armado_colectivo_venta_ids"
SESSION_DESPACHO_SYNC_PENDING = "sirona_despacho_sync_pending"


def _encolar_sync_despacho(request, payloads: list[dict]) -> None:
    if payloads:
        request.session[SESSION_DESPACHO_SYNC_PENDING] = payloads
        request.session.modified = True


def _tomar_sync_despacho_pendiente(request) -> list[dict]:
    payloads = request.session.pop(SESSION_DESPACHO_SYNC_PENDING, None)
    if payloads:
        request.session.modified = True
        return payloads
    return []


def _parse_venta_ids_post(post) -> list[int]:
    return [int(x) for x in post.getlist("venta_id") if str(x).isdigit()]


def _guardar_ventas_sesion(request, venta_ids: list[int]) -> None:
    request.session[SESSION_ARMADO_VENTAS] = venta_ids
    request.session.modified = True


def _ventas_sesion(request) -> list[int]:
    raw = request.session.get(SESSION_ARMADO_VENTAS) or []
    return normalizar_ids_sesion(raw)


def _armado_edit_id_activo(request) -> int | None:
    return armado_edit_id_desde_sesion(request.session)


def _parse_armado_edit_id_post(post) -> int | None:
    raw = (post.get("armado_edit_id") or "").strip()
    return int(raw) if raw.isdigit() else None


def _limpiar_sesion_armado_colectivo(request) -> None:
    for key in (
        SESSION_ARMADO_VENTAS,
        SESSION_ARMADO_PREFILL,
        SESSION_ARMADO_PRESELECT,
        SESSION_ARMADO_EDIT_ID,
    ):
        request.session.pop(key, None)
    request.session.modified = True


def _ctx_armado_colectivo(
    *,
    ventas,
    venta_ids: list[int],
    lineas,
    puntos,
    armado_edit_id: int | None = None,
) -> dict:
    ctx = {
        "ventas": ventas,
        "venta_ids": venta_ids,
        "lineas": lineas,
        "puntos": puntos,
        "modo_edicion": bool(armado_edit_id),
        "armado_edit_id": armado_edit_id,
    }
    if armado_edit_id:
        ctx["armado_editando"] = get_object_or_404(ArmadoColectivoGuardado, pk=armado_edit_id)
    return ctx


def _error_ventas_no_disponibles(request, venta_ids: list[int], armado_edit_id: int | None = None) -> None:
    reservados = venta_ids_reservados_para_lista(armado_edit_id)
    if reservados.intersection(venta_ids):
        messages.error(
            request,
            "Uno o más pedidos ya figuran en un armado colectivo guardado.",
        )
    else:
        messages.error(
            request,
            "Algunos pedidos ya no están disponibles para armado (armados o despachados).",
        )


def _urls_armado_gestion_disponibles() -> bool:
    try:
        reverse("armado_colectivo_editar", kwargs={"pk": 1})
        reverse("armado_colectivo_eliminar", kwargs={"pk": 1})
        return True
    except NoReverseMatch:
        return False


def _armados_guardados_para_lista(request) -> list:
    try:
        return list(armados_colectivos_guardados_lista())
    except (OperationalError, ProgrammingError):
        messages.error(
            request,
            "No se pudieron cargar los armados guardados. Ejecutá las migraciones pendientes de ventas.",
        )
        return []


@login_required
@require_http_methods(["GET"])
def armado_pedidos_lista(request):
    qs = ventas_no_armadas_queryset()
    armado_edit_id = _armado_edit_id_activo(request)
    ventas_reservadas = venta_ids_reservados_para_lista(armado_edit_id)
    preselect_ids = tomar_preselect_ids(request)
    if not preselect_ids and request.GET.get("retomo") == "1":
        preselect_ids = normalizar_ids_sesion(request.session.get(SESSION_ARMADO_VENTAS))
    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(qs, 120)
    page_obj = paginator.get_page(page or 1)
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    armado_editando = None
    if armado_edit_id:
        armado_editando = ArmadoColectivoGuardado.objects.filter(pk=armado_edit_id).first()
        if armado_editando is None:
            request.session.pop(SESSION_ARMADO_EDIT_ID, None)
            request.session.modified = True
            armado_edit_id = None
    return render(
        request,
        "ventas/armado_lista.html",
        {
            "ventas": list(page_obj),
            "page_obj": page_obj,
            "querystring": qcopy.urlencode(),
            "n_no_armados": qs.count(),
            "ventas_reservadas": ventas_reservadas,
            "armados_guardados": _armados_guardados_para_lista(request),
            "preselect_ids": preselect_ids,
            "armado_gestion_urls_ok": _urls_armado_gestion_disponibles(),
            "modo_edicion": bool(armado_edit_id),
            "armado_edit_id": armado_edit_id,
            "armado_editando": armado_editando,
            "despacho_sync_pending": _tomar_sync_despacho_pendiente(request),
        },
    )


@login_required
@require_http_methods(["POST"])
def armado_colectivo(request):
    venta_ids = _parse_venta_ids_post(request.POST)
    if not venta_ids:
        messages.warning(request, "Seleccioná al menos un pedido no armado.")
        return redirect("armado_pedidos_lista")

    armado_edit_id = _armado_edit_id_activo(request)
    ventas = ventas_validas_para_armado_colectivo(venta_ids, armado_edit_id=armado_edit_id)
    if len(ventas) != len(set(venta_ids)):
        _error_ventas_no_disponibles(request, venta_ids, armado_edit_id)
        return redirect("armado_pedidos_lista")

    ids_ok = [v.pk for v in ventas]
    _guardar_ventas_sesion(request, ids_ok)
    lineas = agregar_lineas_armado_colectivo(ids_ok)
    puntos = puntos_stock_armado_lista()
    prefill_wrap = request.session.pop(SESSION_ARMADO_PREFILL, None)
    prefill = None
    if isinstance(prefill_wrap, dict) and set(prefill_wrap.get("venta_ids") or []) == set(ids_ok):
        prefill = prefill_wrap.get("alloc") or {}
    lineas_con_celdas_alloc(lineas, puntos, prefill if prefill else None)

    return render(
        request,
        "ventas/armado_colectivo.html",
        _ctx_armado_colectivo(
            ventas=ventas,
            venta_ids=ids_ok,
            lineas=lineas,
            puntos=puntos,
            armado_edit_id=armado_edit_id,
        ),
    )


@login_required
@require_http_methods(["POST"])
def armado_colectivo_guardar(request):
    venta_ids = _parse_venta_ids_post(request.POST)
    if not venta_ids:
        messages.warning(request, "No hay pedidos para guardar.")
        return redirect("armado_pedidos_lista")

    armado_edit_id = _parse_armado_edit_id_post(request.POST) or _armado_edit_id_activo(request)
    ventas = ventas_validas_para_armado_colectivo(venta_ids, armado_edit_id=armado_edit_id)
    if len(ventas) != len(set(venta_ids)):
        _error_ventas_no_disponibles(request, venta_ids, armado_edit_id)
        return redirect("armado_pedidos_lista")

    ids_ok = [v.pk for v in ventas]
    lineas = agregar_lineas_armado_colectivo(ids_ok)
    puntos = puntos_stock_armado_lista()
    producto_ids = {ln.producto_id for ln in lineas}

    try:
        asignaciones = parse_asignaciones_post(request.POST, producto_ids, puntos)
        err = validar_asignaciones(lineas, asignaciones)
        if err:
            raise ValueError(err)
    except ValueError as exc:
        messages.error(request, str(exc))
        lineas_con_celdas_alloc(lineas, puntos, request.POST)
        return render(
            request,
            "ventas/armado_colectivo.html",
            _ctx_armado_colectivo(
                ventas=ventas,
                venta_ids=ids_ok,
                lineas=lineas,
                puntos=puntos,
                armado_edit_id=armado_edit_id,
            ),
        )

    if armado_edit_id:
        with transaction.atomic():
            actualizar_armado_colectivo(
                armado_edit_id,
                venta_ids=ids_ok,
                lineas=lineas,
                asignaciones=asignaciones,
                puntos=puntos,
            )
            sync_payloads = marcar_pedidos_armados(ids_ok)
        _limpiar_sesion_armado_colectivo(request)
        _encolar_sync_despacho(request, sync_payloads)
        messages.success(request, "Cambios guardados en el armado colectivo.")
        return redirect("armado_colectivo_ver", pk=armado_edit_id)

    with transaction.atomic():
        guardar_armado_colectivo(
            venta_ids=ids_ok,
            lineas=lineas,
            asignaciones=asignaciones,
            puntos=puntos,
            usuario=request.user,
        )
        sync_payloads = marcar_pedidos_armados(ids_ok)
    _limpiar_sesion_armado_colectivo(request)
    _encolar_sync_despacho(request, sync_payloads)
    messages.success(request, "Armado colectivo guardado. Los pedidos ya no se pueden volver a seleccionar.")
    return redirect("armado_pedidos_lista")


@login_required
@require_http_methods(["GET"])
def armado_colectivo_ver(request, pk: int):
    armado = get_object_or_404(
        ArmadoColectivoGuardado.objects.prefetch_related("ventas__vendedor", "ventas__comprador"),
        pk=pk,
    )
    puntos = puntos_stock_armado_lista()
    lineas = lineas_desde_armado_guardado(armado, puntos)
    ventas = list(armado.ventas.all())
    return render(
        request,
        "ventas/armado_colectivo.html",
        {
            "ventas": ventas,
            "venta_ids": [v.pk for v in ventas],
            "lineas": lineas,
            "puntos": puntos,
            "armado_guardado": armado,
            "solo_lectura": True,
            "todos_despachados": all(v.despacho_despachado for v in ventas) if ventas else True,
            "despacho_sync_pending": _tomar_sync_despacho_pendiente(request),
        },
    )


@login_required
@require_http_methods(["POST"])
def armado_colectivo_marcar_despachados(request, pk: int):
    armado = get_object_or_404(
        ArmadoColectivoGuardado.objects.prefetch_related("ventas"),
        pk=pk,
    )
    venta_ids = list(armado.ventas.values_list("pk", flat=True))
    if not venta_ids:
        messages.warning(request, "Este armado no tiene pedidos asociados.")
        return redirect("armado_colectivo_ver", pk=pk)

    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    with transaction.atomic():
        payloads = marcar_pedidos_despachados(venta_ids, usuario=request.user)

    if ajax:
        return JsonResponse({"ok": True, "ventas": payloads})

    n = sum(1 for p in payloads if p.get("despacho_despachado"))
    messages.success(
        request,
        f"Se marcaron {n} pedido(s) como despachados y quedaron archivados.",
    )
    return redirect("armado_colectivo_ver", pk=pk)


@login_required
@require_http_methods(["POST"])
def armado_colectivo_eliminar(request, pk: int):
    armado = get_object_or_404(ArmadoColectivoGuardado, pk=pk)
    nombre = armado.nombre
    if _armado_edit_id_activo(request) == pk:
        _limpiar_sesion_armado_colectivo(request)
    armado.delete()
    messages.success(
        request,
        f"Se eliminó el armado colectivo «{nombre}». Los pedidos vuelven a estar disponibles.",
    )
    return redirect("armado_pedidos_lista")


@login_required
@require_http_methods(["POST"])
def armado_colectivo_editar(request, pk: int):
    armado = get_object_or_404(
        ArmadoColectivoGuardado.objects.prefetch_related("ventas"),
        pk=pk,
    )
    venta_ids, prefill = preparar_edicion_armado(armado)
    if not venta_ids:
        armado.delete()
        messages.warning(request, "El armado no tenía pedidos y fue eliminado.")
        return redirect("armado_pedidos_lista")

    request.session[SESSION_ARMADO_EDIT_ID] = armado.pk
    request.session[SESSION_ARMADO_PRESELECT] = list(venta_ids)
    if prefill:
        request.session[SESSION_ARMADO_PREFILL] = {"venta_ids": venta_ids, "alloc": prefill}
    request.session.modified = True
    messages.info(
        request,
        "Modificá pedidos o cantidades. Los cambios solo se aplican al pulsar «Guardar cambios».",
    )
    return redirect("armado_pedidos_lista")


@login_required
@require_http_methods(["POST"])
def armado_colectivo_cancelar_edicion(request):
    armado_edit_id = _armado_edit_id_activo(request)
    _limpiar_sesion_armado_colectivo(request)
    messages.info(request, "Se descartaron los cambios. El armado colectivo quedó como estaba.")
    if armado_edit_id:
        return redirect("armado_colectivo_ver", pk=armado_edit_id)
    return redirect("armado_pedidos_lista")


@login_required
@require_http_methods(["GET"])
def armado_colectivo_guardado_pdf(request, pk: int):
    armado = get_object_or_404(
        ArmadoColectivoGuardado.objects.prefetch_related("ventas", "lineas__asignaciones__punto"),
        pk=pk,
    )
    puntos = puntos_stock_armado_lista()
    ventas = list(armado.ventas.all())
    asignaciones = asignaciones_desde_armado_guardado(armado)
    lineas = lineas_armado_colectivo_desde_guardado(armado)

    return armado_colectivo_pdf_response(
        ventas=ventas,
        lineas=lineas,
        puntos=puntos,
        asignaciones=asignaciones,
    )


@login_required
@require_http_methods(["POST"])
def armado_colectivo_pdf(request):
    venta_ids = _parse_venta_ids_post(request.POST)
    if not venta_ids:
        venta_ids = _ventas_sesion(request)
    if not venta_ids:
        messages.error(request, "No hay pedidos seleccionados para imprimir.")
        return redirect("armado_pedidos_lista")

    armado_edit_id = _parse_armado_edit_id_post(request.POST) or _armado_edit_id_activo(request)
    ventas = ventas_validas_para_armado_colectivo(venta_ids, armado_edit_id=armado_edit_id)
    if len(ventas) != len(set(venta_ids)):
        _error_ventas_no_disponibles(request, venta_ids, armado_edit_id)
        return redirect("armado_pedidos_lista")

    ids_ok = [v.pk for v in ventas]
    lineas = agregar_lineas_armado_colectivo(ids_ok)
    puntos = puntos_stock_armado_lista()
    producto_ids = {ln.producto_id for ln in lineas}

    try:
        asignaciones = parse_asignaciones_post(request.POST, producto_ids, puntos)
    except ValueError as exc:
        messages.error(request, str(exc))
        lineas_con_celdas_alloc(lineas, puntos, request.POST)
        return render(
            request,
            "ventas/armado_colectivo.html",
            _ctx_armado_colectivo(
                ventas=ventas,
                venta_ids=ids_ok,
                lineas=lineas,
                puntos=puntos,
                armado_edit_id=armado_edit_id,
            ),
        )

    err = validar_asignaciones(lineas, asignaciones)
    if err:
        messages.error(request, err)
        lineas_con_celdas_alloc(lineas, puntos, request.POST)
        return render(
            request,
            "ventas/armado_colectivo.html",
            _ctx_armado_colectivo(
                ventas=ventas,
                venta_ids=ids_ok,
                lineas=lineas,
                puntos=puntos,
                armado_edit_id=armado_edit_id,
            ),
        )

    inline = request.GET.get("inline") == "1" or request.POST.get("inline") == "1"
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    pdf_only = request.POST.get("_pdf_only") == "1"

    if not pdf_only:
        with transaction.atomic():
            sync_payloads = marcar_pedidos_armados(ids_ok)
    else:
        sync_payloads = []

    if ajax:
        return JsonResponse({"ok": True, "ventas": sync_payloads})

    resp = armado_colectivo_pdf_response(
        ventas=ventas,
        lineas=lineas,
        puntos=puntos,
        asignaciones=asignaciones,
    )
    if not inline:
        resp["Content-Disposition"] = 'attachment; filename="armado-colectivo.pdf"'

    request.session.pop(SESSION_ARMADO_VENTAS, None)
    request.session.modified = True
    return resp


@login_required
@require_http_methods(["GET"])
def puntos_stock_modal(request):
    return render(
        request,
        "ventas/puntos_stock_modal.html",
        {"puntos": puntos_stock_armado_lista()},
    )


@staff_required
@require_http_methods(["POST"])
def puntos_stock_guardar(request):
    accion = (request.POST.get("accion") or "").strip()
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _json_ok(msg: str, puntos=None):
        if ajax:
            data = {"ok": True, "message": msg}
            if puntos is not None:
                data["puntos"] = puntos
            return JsonResponse(data)
        messages.success(request, msg)
        return redirect("armado_pedidos_lista")

    def _json_err(msg: str, status=400):
        if ajax:
            return JsonResponse({"error": msg}, status=status)
        messages.error(request, msg)
        return redirect("armado_pedidos_lista")

    puntos_payload = lambda: [{"id": p.pk, "nombre": p.nombre, "orden": p.orden} for p in puntos_stock_armado_lista()]

    if accion == "crear":
        nombre = (request.POST.get("nombre") or "").strip()
        if not nombre:
            return _json_err("Ingresá un nombre para el punto de stock.")
        if PuntoStockArmado.objects.filter(nombre__iexact=nombre).exists():
            return _json_err("Ya existe un punto de stock con ese nombre.")
        max_ord = PuntoStockArmado.objects.order_by("-orden").values_list("orden", flat=True).first() or 0
        PuntoStockArmado.objects.create(nombre=nombre, orden=int(max_ord) + 1)
        return _json_ok(f"Punto de stock «{nombre}» agregado.", puntos_payload())

    if accion == "editar":
        raw_id = (request.POST.get("punto_id") or "").strip()
        if not raw_id.isdigit():
            return _json_err("Punto no válido.")
        punto = get_object_or_404(PuntoStockArmado, pk=int(raw_id))
        nombre = (request.POST.get("nombre") or "").strip()
        if not nombre:
            return _json_err("El nombre no puede quedar vacío.")
        if PuntoStockArmado.objects.filter(nombre__iexact=nombre).exclude(pk=punto.pk).exists():
            return _json_err("Ya existe otro punto con ese nombre.")
        punto.nombre = nombre
        punto.save(update_fields=["nombre"])
        return _json_ok("Punto de stock actualizado.", puntos_payload())

    if accion == "eliminar":
        raw_id = (request.POST.get("punto_id") or "").strip()
        if not raw_id.isdigit():
            return _json_err("Punto no válido.")
        punto = get_object_or_404(PuntoStockArmado, pk=int(raw_id))
        if PuntoStockArmado.objects.count() <= 1:
            return _json_err("Debe quedar al menos un punto de stock.")
        nombre = punto.nombre
        punto.delete()
        return _json_ok(f"Se eliminó «{nombre}».", puntos_payload())

    return _json_err("Acción no reconocida.")
