"""Gestión de listas de precios por rubro (Farmacia = precios en Producto; otras = ListaPrecioItem)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When
from django.http import Http404, HttpResponseForbidden
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.authz import staff_required
from core.money_decimal import format_monto_ars, q2

from .lista_precios_pdf import (
    build_png_export_payload,
    filas_lista_precios,
    lista_precios_pdf_file_response,
    lista_precios_xlsx_response,
)
from .models import ListaPrecioItem, ListaPrecios, Producto

# Borrador de nombre para el paso de confirmación al crear una lista nueva (session key).
SESSION_LISTA_PRECIO_NUEVA_NOMBRE = "lista_precio_nueva_nombre"


def _lista_precios_ids_post(request) -> set[int]:
    return {int(x) for x in request.POST.getlist("listas_extra") if str(x).isdigit()}


def producto_listas_ids_post(request) -> set[int]:
    ids = _lista_precios_ids_post(request)
    return set(ListaPrecios.objects.filter(pk__in=ids).values_list("pk", flat=True))


def producto_tiene_lista_precio_en_post(request) -> bool:
    return bool(producto_listas_ids_post(request))


def producto_listas_extra_context(
    producto: Producto | None,
    *,
    selected_ids: set[int] | None = None,
) -> dict:
    opciones = ListaPrecios.objects.all().order_by("-es_farmacia", "nombre")
    marcados: set[int] = set()
    if selected_ids is not None:
        marcados = selected_ids
    elif producto and producto.pk:
        marcados = set(
            ListaPrecioItem.objects.filter(producto=producto).values_list("lista_id", flat=True)
        )
        farmacia_id = (
            ListaPrecios.objects.filter(es_farmacia=True)
            .order_by("id")
            .values_list("pk", flat=True)
            .first()
        )
        if farmacia_id and producto.en_lista_precios:
            marcados.add(farmacia_id)
    return {
        "listas_extra_opciones": opciones,
        "listas_extra_marcados": marcados,
    }


def sync_producto_listas_extras_from_post(request, producto: Producto) -> None:
    """Asocia el producto a las listas marcadas en el formulario."""
    if request.POST.get("listas_extra_present") != "1":
        return
    ids = _lista_precios_ids_post(request)
    listas = list(ListaPrecios.objects.filter(pk__in=ids))
    farmacia_marcada = any(lista.es_farmacia for lista in listas)
    if producto.en_lista_precios != farmacia_marcada:
        producto.en_lista_precios = farmacia_marcada
        producto.save(update_fields=["en_lista_precios"])

    listas_ids = {lista.pk for lista in listas if not lista.es_farmacia}
    ListaPrecioItem.objects.filter(producto=producto).exclude(lista_id__in=listas_ids).delete()
    for lista in (lista for lista in listas if not lista.es_farmacia):
        ListaPrecioItem.objects.get_or_create(
            lista=lista,
            producto=producto,
            defaults={"precio_venta": producto.precio_venta},
        )


def _parse_precio(raw: str) -> Decimal | None:
    s = (raw or "").strip().replace(",", ".")
    if s == "":
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    if d < 0:
        return None
    return q2(d)


@login_required
@require_http_methods(["GET"])
def listas_precios_menu(request):
    if request.GET.get("cancel_nueva") == "1":
        request.session.pop(SESSION_LISTA_PRECIO_NUEVA_NOMBRE, None)
        messages.info(request, "No se creó ninguna lista.")
        return redirect("productos_listas_precios")
    listas = list(ListaPrecios.objects.all().order_by("-es_farmacia", "nombre"))
    return render(request, "productos/listas_precios_index.html", {"listas": listas})


@login_required
@require_http_methods(["GET", "POST"])
def lista_precios_nueva(request):
    if request.method == "GET" and request.GET.get("cancel") == "1":
        request.session.pop(SESSION_LISTA_PRECIO_NUEVA_NOMBRE, None)
        messages.info(request, "No se creó ninguna lista.")
        return redirect("productos_listas_precios")
    if request.method == "POST":
        nombre = (request.POST.get("nombre") or "").strip()
        if not nombre:
            messages.error(request, "Ingresá un nombre para la lista.")
            return redirect("productos_listas_precios")
        if ListaPrecios.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, "Ya existe una lista con ese nombre.")
            return redirect("productos_listas_precios")
        request.session[SESSION_LISTA_PRECIO_NUEVA_NOMBRE] = nombre
        return redirect("lista_precios_nueva_confirmar")
    nombre_borrador = (request.session.get(SESSION_LISTA_PRECIO_NUEVA_NOMBRE) or "").strip()
    return render(
        request,
        "productos/lista_precios_nueva.html",
        {"nombre_borrador": nombre_borrador},
    )


@login_required
@require_http_methods(["GET", "POST"])
def lista_precios_nueva_confirmar(request):
    nombre = request.session.get(SESSION_LISTA_PRECIO_NUEVA_NOMBRE)
    if not nombre:
        messages.warning(request, "No hay ninguna lista pendiente de confirmación.")
        return redirect("lista_precios_nueva")
    if request.method == "POST":
        if request.POST.get("confirmar") != "1":
            request.session.pop(SESSION_LISTA_PRECIO_NUEVA_NOMBRE, None)
            messages.info(request, "Creación cancelada.")
            return redirect("productos_listas_precios")
        nombre = request.session.pop(SESSION_LISTA_PRECIO_NUEVA_NOMBRE, None)
        if not nombre:
            messages.error(request, "La sesión expiró. Volvé a ingresar el nombre.")
            return redirect("lista_precios_nueva")
        if ListaPrecios.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, "Ya existe una lista con ese nombre.")
            return redirect("productos_listas_precios")
        lista = ListaPrecios.objects.create(nombre=nombre)
        messages.success(request, f"Lista creada: {lista.nombre}")
        return redirect("lista_precios_trabajar", pk=lista.pk)
    return render(request, "productos/lista_precios_nueva_confirmar.html", {"nombre": nombre})


@login_required
@require_http_methods(["GET", "POST"])
def lista_precios_renombrar(request, pk: int):
    lista = get_object_or_404(ListaPrecios, pk=pk)
    if lista.es_farmacia:
        return HttpResponseForbidden("La lista Farmacia no se puede renombrar.")
    if request.method == "POST":
        nombre = (request.POST.get("nombre") or "").strip()
        if not nombre:
            messages.error(request, "El nombre no puede quedar vacío.")
        elif ListaPrecios.objects.filter(nombre__iexact=nombre).exclude(pk=lista.pk).exists():
            messages.error(request, "Ya existe otra lista con ese nombre.")
        else:
            lista.nombre = nombre
            lista.slug = ""
            lista.save()
            messages.success(request, "Lista actualizada.")
            return redirect("lista_precios_trabajar", pk=lista.pk)
    return render(request, "productos/lista_precios_renombrar.html", {"lista": lista})


@staff_required
@require_http_methods(["POST"])
def lista_precios_eliminar(request, pk: int):
    lista = get_object_or_404(ListaPrecios, pk=pk)
    if lista.es_farmacia:
        messages.error(request, "La lista Farmacia no se puede eliminar.")
        return redirect("productos_listas_precios")
    nombre = lista.nombre
    lista.delete()
    messages.success(request, f"Lista eliminada: {nombre}")
    return redirect("productos_listas_precios")


@login_required
@require_http_methods(["GET", "POST"])
def lista_precios_trabajar(request, pk: int):
    lista = get_object_or_404(ListaPrecios, pk=pk)
    q = (request.GET.get("q") or request.POST.get("q") or "").strip()
    page = (request.GET.get("page") or "").strip()
    page_disp = (request.GET.get("page_disp") or "").strip()

    if lista.es_farmacia:
        qs_all = Producto.objects.filter(habilitado=True, en_lista_precios=True).order_by(
            "tipo", "descripcion", "codigo"
        )
        productos_picker = list(
            qs_all.values("codigo", "descripcion")[:3000]
        )
        qs = qs_all
        if q:
            qs = qs.filter(Q(descripcion__icontains=q) | Q(codigo__icontains=q))
        paginator = Paginator(qs, 120)
        page_obj = paginator.get_page(page or 1)
        productos = list(page_obj)

        if request.method == "POST":
            actualizados = 0
            to_update: list[Producto] = []
            with transaction.atomic():
                for p in productos:
                    key = f"pv_{p.pk}"
                    if key not in request.POST:
                        continue
                    pr = _parse_precio(request.POST.get(key) or "")
                    if pr is None:
                        continue
                    if p.precio_venta != pr:
                        p.precio_venta = pr
                        p.precio_venta_editado = True
                        to_update.append(p)
                        actualizados += 1
                if to_update:
                    Producto.objects.bulk_update(to_update, ["precio_venta", "precio_venta_editado"])
            messages.success(request, f"Se actualizaron {actualizados} precio(s) de Farmacia.")
            return redirect(f"{request.path}?q={q}" if q else request.path)

        return render(
            request,
            "productos/lista_precios_trabajar_farmacia.html",
            {
                "lista": lista,
                "productos": productos,
                "q": q,
                "page_obj": page_obj,
                "productos_picker": productos_picker,
            },
        )

    # Listas por rubro: ítems con precio propio
    if request.method == "POST":
        accion = (request.POST.get("accion") or "").strip()
        quitar = (request.POST.get("quitar_item") or "").strip()
        if accion == "renombrar":
            nombre = (request.POST.get("nombre") or "").strip()
            if not nombre:
                messages.error(request, "El nombre no puede quedar vacío.")
                return redirect(f"{request.path}?q={q}" if q else request.path)
            if ListaPrecios.objects.filter(nombre__iexact=nombre).exclude(pk=lista.pk).exists():
                messages.error(request, "Ya existe otra lista con ese nombre.")
                return redirect(f"{request.path}?q={q}" if q else request.path)
            lista.nombre = nombre
            lista.slug = ""
            lista.save(update_fields=["nombre", "slug"])
            messages.success(request, "Nombre de lista actualizado.")
            return redirect(f"{request.path}?q={q}" if q else request.path)
        if quitar.isdigit():
            ListaPrecioItem.objects.filter(pk=int(quitar), lista=lista).delete()
            messages.info(request, "Producto quitado de la lista.")
            return redirect(f"{request.path}?q={q}" if q else request.path)
        if accion == "agregar":
            raw_pid = (request.POST.get("producto_id") or "").strip()
            if raw_pid.isdigit():
                prod = Producto.objects.filter(pk=int(raw_pid), habilitado=True).first()
                if prod:
                    ListaPrecioItem.objects.get_or_create(
                        lista=lista,
                        producto=prod,
                        defaults={"precio_venta": prod.precio_venta},
                    )
                    messages.success(request, f"Agregado a la lista: {prod.codigo}")
                else:
                    messages.warning(request, "Producto no encontrado o deshabilitado.")
            return redirect(f"{request.path}?q={q}" if q else request.path)

        items = ListaPrecioItem.objects.filter(lista=lista).select_related("producto")
        n = 0
        to_update: list[ListaPrecioItem] = []
        with transaction.atomic():
            for it in items:
                key = f"ip_{it.pk}"
                if key not in request.POST:
                    continue
                pr = _parse_precio(request.POST.get(key) or "")
                if pr is None:
                    continue
                if it.precio_venta != pr:
                    it.precio_venta = pr
                    to_update.append(it)
                    n += 1
            if to_update:
                ListaPrecioItem.objects.bulk_update(to_update, ["precio_venta"])
        messages.success(request, f"Se guardaron {n} precio(s) de la lista.")
        return redirect(f"{request.path}?q={q}" if q else request.path)

    items_all = (
        ListaPrecioItem.objects.filter(lista=lista)
        .select_related("producto")
        .order_by("producto__tipo", "producto__descripcion", "producto__codigo")
    )
    productos_picker = [
        {"codigo": r["producto__codigo"], "descripcion": r["producto__descripcion"]}
        for r in items_all.values("producto__codigo", "producto__descripcion")[:3000]
    ]
    items = items_all
    if q:
        items = items.filter(
            Q(producto__descripcion__icontains=q) | Q(producto__codigo__icontains=q)
        )
    paginator = Paginator(items, 120)
    page_obj = paginator.get_page(page or 1)
    items = list(page_obj)

    en_lista_ids = {it.producto_id for it in items}
    disp_qs = (
        Producto.objects.filter(habilitado=True)
        .exclude(pk__in=en_lista_ids)
        .order_by("tipo", "descripcion", "codigo")
    )
    disp_paginator = Paginator(disp_qs, 120)
    page_disp_obj = disp_paginator.get_page(page_disp or 1)
    disponibles = list(page_disp_obj)

    return render(
        request,
        "productos/lista_precios_trabajar_rubro.html",
        {
            "lista": lista,
            "items": items,
            "disponibles": disponibles,
            "q": q,
            "page_obj": page_obj,
            "page_disp_obj": page_disp_obj,
            "productos_picker": productos_picker,
        },
    )


@login_required
@require_http_methods(["GET"])
def lista_precios_ver(request, pk: int):
    """Vista de solo lectura con membrete y enlaces a exportar PDF/PNG."""
    lista = get_object_or_404(ListaPrecios, pk=pk)
    q = (request.GET.get("q") or "").strip()
    page = (request.GET.get("page") or "").strip()
    emitido_en = timezone.localtime()

    if lista.es_farmacia:
        qs_all = Producto.objects.filter(habilitado=True, en_lista_precios=True).order_by(
            "tipo", "descripcion", "codigo"
        )
        productos_picker = list(qs_all.values("codigo", "descripcion")[:3000])
        qs = qs_all
        if q:
            qs = qs.filter(Q(descripcion__icontains=q) | Q(codigo__icontains=q))
        kpi = qs.aggregate(
            productos=Count("id"),
            activos=Count("id", filter=Q(habilitado=True)),
            valor_total=Sum("precio_venta"),
            stock_total=Sum("stock"),
            sin_stock=Count("id", filter=Q(stock__lte=0)),
        )
        # Margen promedio estimado: (precio - costo)/costo. Evita división por cero.
        margen_pct = ExpressionWrapper(
            (F("precio_venta") - F("costo")) * Value(100.0) / F("costo"),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        )
        kpi["margen_prom"] = (
            qs.aggregate(
                m=Avg(
                    Case(
                        When(costo__gt=0, then=margen_pct),
                        default=None,
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                )
            ).get("m")
            or Decimal("0.00")
        )
        paginator = Paginator(qs, 120)
        page_obj = paginator.get_page(page or 1)
        url_publica_cliente = request.build_absolute_uri(
            reverse("lista_precios_public_cliente", kwargs={"slug": lista.slug})
        )
        return render(
            request,
            "productos/lista_precios_ver.html",
            {
                "lista": lista,
                "es_farmacia": True,
                "productos": list(page_obj),
                "page_obj": page_obj,
                "q": q,
                "emitido_en": emitido_en,
                "kpi": kpi,
                "productos_picker": productos_picker,
                "url_publica_cliente": url_publica_cliente,
            },
        )

    items_all = (
        ListaPrecioItem.objects.filter(lista=lista)
        .select_related("producto")
        .order_by("producto__tipo", "producto__descripcion", "producto__codigo")
    )
    productos_picker = [
        {"codigo": r["producto__codigo"], "descripcion": r["producto__descripcion"]}
        for r in items_all.values("producto__codigo", "producto__descripcion")[:3000]
    ]
    items = items_all
    if q:
        items = items.filter(
            Q(producto__descripcion__icontains=q) | Q(producto__codigo__icontains=q)
        )
    kpi = items.aggregate(
        productos=Count("id"),
        activos=Count("id", filter=Q(producto__habilitado=True)),
        valor_total=Sum("precio_venta"),
        stock_total=Sum("producto__stock"),
        sin_stock=Count("id", filter=Q(producto__stock__lte=0)),
        margen_prom=Avg(
            Case(
                When(producto__costo__gt=0, then=(F("precio_venta") - F("producto__costo")) * Value(100.0) / F("producto__costo")),
                default=None,
                output_field=DecimalField(max_digits=10, decimal_places=2),
            )
        ),
    )
    paginator = Paginator(items, 120)
    page_obj = paginator.get_page(page or 1)
    url_publica_cliente = request.build_absolute_uri(
        reverse("lista_precios_public_cliente", kwargs={"slug": lista.slug})
    )
    return render(
        request,
        "productos/lista_precios_ver.html",
        {
            "lista": lista,
            "es_farmacia": False,
            "items": list(page_obj),
            "page_obj": page_obj,
            "q": q,
            "emitido_en": emitido_en,
            "kpi": kpi,
            "productos_picker": productos_picker,
            "url_publica_cliente": url_publica_cliente,
        },
    )


@require_http_methods(["GET"])
def lista_precios_public_cliente(request, slug: str):
    """
    Vista pública minimalista (sin menú app): solo nombre de lista, búsqueda y tabla de precios.
    Pensada para compartir por WhatsApp / QR con el mismo estilo de link absoluto.
    """
    lista = get_object_or_404(ListaPrecios, slug=slug)
    q = (request.GET.get("q") or "").strip()
    page = (request.GET.get("page") or "").strip()
    emitido_en = timezone.localtime()

    if lista.es_farmacia:
        qs_all = Producto.objects.filter(habilitado=True, en_lista_precios=True).order_by(
            "tipo", "descripcion", "codigo"
        )
        qs = qs_all
        if q:
            qs = qs.filter(Q(descripcion__icontains=q) | Q(codigo__icontains=q))
        paginator = Paginator(qs, 120)
        page_obj = paginator.get_page(page or 1)
        return render(
            request,
            "productos/lista_precios_public_cliente.html",
            {
                "lista": lista,
                "es_farmacia": True,
                "productos": list(page_obj),
                "page_obj": page_obj,
                "q": q,
                "emitido_en": emitido_en,
            },
        )

    items_all = (
        ListaPrecioItem.objects.filter(lista=lista)
        .select_related("producto")
        .order_by("producto__tipo", "producto__descripcion", "producto__codigo")
    )
    items = items_all
    if q:
        items = items.filter(
            Q(producto__descripcion__icontains=q) | Q(producto__codigo__icontains=q)
        )
    paginator = Paginator(items, 120)
    page_obj = paginator.get_page(page or 1)
    return render(
        request,
        "productos/lista_precios_public_cliente.html",
        {
            "lista": lista,
            "es_farmacia": False,
            "items": list(page_obj),
            "page_obj": page_obj,
            "q": q,
            "emitido_en": emitido_en,
        },
    )


@login_required
@require_http_methods(["GET"])
def lista_precios_export_pdf(request, pk: int):
    lista = get_object_or_404(ListaPrecios, pk=pk)
    return lista_precios_pdf_file_response(lista=lista)


@login_required
@require_http_methods(["GET"])
def lista_precios_export_excel(request, pk: int):
    lista = get_object_or_404(ListaPrecios, pk=pk)
    return lista_precios_xlsx_response(lista=lista)


@login_required
@require_http_methods(["GET"])
def lista_precios_export_png(request, pk: int):
    lista = get_object_or_404(ListaPrecios, pk=pk)
    q = (request.GET.get("q") or "").strip()
    filas = filas_lista_precios(lista)
    if q:
        ql = q.lower()
        filas = [(p, precio) for (p, precio) in filas if ql in (p.descripcion or "").lower() or ql in (p.codigo or "").lower()]

    png_export = build_png_export_payload(filas)

    total_valor = Decimal("0.00")
    for _, precio in filas:
        try:
            total_valor += Decimal(precio or 0)
        except Exception:
            pass
    kpi = {
        "productos": len(filas),
        "valor_total": format_monto_ars(total_valor),
    }
    return render(
        request,
        "productos/lista_precios_compartir.html",
        {
            "lista": lista,
            "titulo": f"Lista de precios — {lista.nombre}",
            "png_export": png_export,
            "q": q,
            "kpi": kpi,
        },
    )


@require_http_methods(["GET"])
def lista_precios_public_farmacia_png(request):
    """
    Endpoint público (para QR ya impresos vía Sheet):
    muestra una página que genera un PNG completo de la lista Farmacia en el momento.
    """
    lista = ListaPrecios.objects.filter(es_farmacia=True).order_by("id").first()
    if lista is None:
        raise Http404("No existe lista Farmacia.")

    q = (request.GET.get("q") or "").strip()
    filas = filas_lista_precios(lista)
    if q:
        ql = q.lower()
        filas = [
            (p, precio)
            for (p, precio) in filas
            if ql in (p.descripcion or "").lower() or ql in (p.codigo or "").lower()
        ]

    png_export = build_png_export_payload(filas)

    total_valor = Decimal("0.00")
    for _, precio in filas:
        try:
            total_valor += Decimal(precio or 0)
        except Exception:
            pass
    kpi = {
        "productos": len(filas),
        "valor_total": format_monto_ars(total_valor),
    }
    return render(
        request,
        "productos/lista_precios_public_png.html",
        {
            "lista": lista,
            "titulo": "Lista de precios — Farmacia",
            "png_export": png_export,
            "q": q,
            "kpi": kpi,
            "public": True,
        },
    )
