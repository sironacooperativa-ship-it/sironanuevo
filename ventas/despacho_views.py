"""Vistas de despachos: armado colectivo y puntos de stock."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.authz import staff_required

from .armado_colectivo_pdf import armado_colectivo_pdf_response
from .armado_servicios import (
    agregar_lineas_armado_colectivo,
    lineas_con_celdas_alloc,
    parse_asignaciones_post,
    puntos_stock_armado_lista,
    validar_asignaciones,
    ventas_no_armadas_queryset,
    ventas_validas_para_armado_colectivo,
)
from .models import PuntoStockArmado, Venta

SESSION_ARMADO_VENTAS = "armado_colectivo_venta_ids"


def _parse_venta_ids_post(post) -> list[int]:
    return [int(x) for x in post.getlist("venta_id") if str(x).isdigit()]


def _guardar_ventas_sesion(request, venta_ids: list[int]) -> None:
    request.session[SESSION_ARMADO_VENTAS] = venta_ids
    request.session.modified = True


def _ventas_sesion(request) -> list[int]:
    raw = request.session.get(SESSION_ARMADO_VENTAS) or []
    return [int(x) for x in raw if str(x).isdigit()]


@login_required
@require_http_methods(["GET"])
def armado_pedidos_lista(request):
    qs = ventas_no_armadas_queryset()
    page = (request.GET.get("page") or "").strip()
    paginator = Paginator(qs, 120)
    page_obj = paginator.get_page(page or 1)
    qcopy = request.GET.copy()
    qcopy.pop("page", None)
    return render(
        request,
        "ventas/armado_lista.html",
        {
            "ventas": list(page_obj),
            "page_obj": page_obj,
            "querystring": qcopy.urlencode(),
            "n_no_armados": qs.count(),
        },
    )


@login_required
@require_http_methods(["POST"])
def armado_colectivo(request):
    venta_ids = _parse_venta_ids_post(request)
    if not venta_ids:
        messages.warning(request, "Seleccioná al menos un pedido no armado.")
        return redirect("armado_pedidos_lista")

    ventas = ventas_validas_para_armado_colectivo(venta_ids)
    if len(ventas) != len(set(venta_ids)):
        messages.error(request, "Algunos pedidos ya no están disponibles para armado (armados o despachados).")
        return redirect("armado_pedidos_lista")

    ids_ok = [v.pk for v in ventas]
    _guardar_ventas_sesion(request, ids_ok)
    lineas = agregar_lineas_armado_colectivo(ids_ok)
    puntos = puntos_stock_armado_lista()
    lineas_con_celdas_alloc(lineas, puntos)

    return render(
        request,
        "ventas/armado_colectivo.html",
        {
            "ventas": ventas,
            "venta_ids": ids_ok,
            "lineas": lineas,
            "puntos": puntos,
        },
    )


@login_required
@require_http_methods(["POST"])
def armado_colectivo_pdf(request):
    venta_ids = _parse_venta_ids_post(request)
    if not venta_ids:
        venta_ids = _ventas_sesion(request)
    if not venta_ids:
        messages.error(request, "No hay pedidos seleccionados para imprimir.")
        return redirect("armado_pedidos_lista")

    ventas = ventas_validas_para_armado_colectivo(venta_ids)
    if len(ventas) != len(set(venta_ids)):
        messages.error(request, "Los pedidos seleccionados cambiaron. Volvé a generar el armado colectivo.")
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
            {
                "ventas": ventas,
                "venta_ids": ids_ok,
                "lineas": lineas,
                "puntos": puntos,
            },
        )

    err = validar_asignaciones(lineas, asignaciones)
    if err:
        messages.error(request, err)
        lineas_con_celdas_alloc(lineas, puntos, request.POST)
        return render(
            request,
            "ventas/armado_colectivo.html",
            {
                "ventas": ventas,
                "venta_ids": ids_ok,
                "lineas": lineas,
                "puntos": puntos,
            },
        )

    inline = request.GET.get("inline") == "1" or request.POST.get("inline") == "1"
    resp = armado_colectivo_pdf_response(
        ventas=ventas,
        lineas=lineas,
        puntos=puntos,
        asignaciones=asignaciones,
    )
    if not inline:
        resp["Content-Disposition"] = 'attachment; filename="armado-colectivo.pdf"'

    with transaction.atomic():
        Venta.objects.filter(pk__in=ids_ok).update(despacho_armado=True)

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
