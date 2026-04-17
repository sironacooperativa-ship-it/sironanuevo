import math
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.http import FileResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from openpyxl import load_workbook
from urllib.parse import urlencode

from core.export_utils import parse_export, pdf_response, xlsx_response
from core.money_decimal import format_monto_ars, q2
from core.pdf_membrete import platypus_membrete
from personas.models import Proveedor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from .forms import ProductoForm
from .models import ListaPrecios, Producto


def _redirect_productos_con_filtros(request):
    """Vuelve al listado conservando búsqueda / filtros enviados como retorno_* en POST."""
    params = {}
    for k in ("q", "tipo", "proveedor"):
        v = (request.POST.get(f"retorno_{k}") or "").strip()
        if v:
            params[k] = v
    url = reverse("productos_list")
    if params:
        url += "?" + urlencode(params)
    return redirect(url)


def _filtrar_productos_queryset(request, *, use_post: bool = False):
    """Filtra por búsqueda, tipo y proveedor (productos con al menos una compra a ese proveedor)."""
    if use_post:
        q = (request.POST.get("filtro_q") or "").strip()
        tipo = (request.POST.get("filtro_tipo") or "").strip()
        proveedor = (request.POST.get("filtro_proveedor") or "").strip()
    else:
        q = (request.GET.get("q") or "").strip()
        tipo = (request.GET.get("tipo") or "").strip()
        proveedor = (request.GET.get("proveedor") or "").strip()

    productos = Producto.objects.all().order_by("descripcion", "codigo")
    if q:
        productos = productos.filter(Q(descripcion__icontains=q) | Q(codigo__icontains=q))
    if tipo:
        productos = productos.filter(tipo=tipo)
    if proveedor.isdigit():
        productos = productos.filter(compras_origen__proveedor_id=int(proveedor)).distinct()

    return productos, {"q": q, "tipo": tipo, "proveedor": proveedor}


def _parse_pct_aumento(request) -> Decimal | None:
    raw = (request.POST.get("pct_aumento") or "").strip().replace(",", ".")
    if raw == "":
        return None
    try:
        d = Decimal(raw)
    except InvalidOperation:
        return None
    if d < 0 or d > Decimal("999.99"):
        return None
    return d


def _parse_precio_venta_input(raw: str) -> Decimal | None:
    s = (raw or "").strip().replace(",", ".")
    if s == "":
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if d < 0:
        return None
    return q2(d)


def _redirect_productos_aumento_filtros(request):
    qstr = urlencode(
        {
            "q": (request.POST.get("filtro_q") or "").strip(),
            "tipo": (request.POST.get("filtro_tipo") or "").strip(),
            "proveedor": (request.POST.get("filtro_proveedor") or "").strip(),
        }
    )
    url = reverse("productos_aumento")
    if qstr:
        url += "?" + qstr
    return redirect(url)


def _celda_texto(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isfinite(v) and abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return str(v).strip()
    return str(v).strip()


def _codigo_desde_celda(v) -> str:
    return _celda_texto(v)[:6]


def _parse_decimal_celda(v, *, default: Decimal) -> Decimal:
    if v is None:
        return default
    s = _celda_texto(v)
    if s == "":
        return default
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"valor numérico inválido ({s!r})") from exc


def _parse_opcional_decimal(v) -> Decimal | None:
    if v is None:
        return None
    s = _celda_texto(v)
    if s == "":
        return None
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"valor numérico inválido ({s!r})") from exc


def _sin_acentos(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _resolver_tipo_producto(tipo_raw: str) -> str | None:
    """
    Acepta mayúsculas/minúsculas, acentos y palabras parecidas
    (p. ej. medicamento/medicamentos, accesorio, otros).
    Devuelve Producto.Tipo.* o None.
    """
    s = _sin_acentos(tipo_raw.strip()).lower()
    s = " ".join(s.split())
    if not s:
        return None

    if s in ("med", "me"):
        return Producto.Tipo.MEDICAMENTOS
    if s == "ac":
        return Producto.Tipo.ACCESORIOS
    if s == "ot":
        return Producto.Tipo.OTROS

    if s.startswith("medic"):
        return Producto.Tipo.MEDICAMENTOS
    if s.startswith("acces"):
        return Producto.Tipo.ACCESORIOS

    if s in ("otros", "otro", "otr"):
        return Producto.Tipo.OTROS
    if s.startswith("otr") and not s.startswith("otra"):
        return Producto.Tipo.OTROS

    return None


# Importación Excel: índices por defecto (fila 1 = encabezados del modelo) y aliases de columnas
_IMPORT_COL_FIXED = {
    "codigo": 0,
    "descripcion": 1,
    "tipo": 2,
    "costo": 3,
    "porcentaje_ganancia": 4,
    "precio_venta": 5,
    "stock": 6,
    "fecha_vencimiento": 7,
}

_COLUMN_ALIAS_ORDER: list[tuple[str, frozenset[str]]] = [
    ("codigo", frozenset({"codigo", "code"})),
    ("descripcion", frozenset({"descripcion", "desc", "producto", "nombre"})),
    ("tipo", frozenset({"tipo", "type", "categoria", "rubro"})),
    ("costo", frozenset({"costo", "cost"})),
    (
        "porcentaje_ganancia",
        frozenset({"porcentaje_ganancia", "porcentaje", "ganancia", "margen", "%_gan", "%"}),
    ),
    ("precio_venta", frozenset({"precio_venta", "pvp", "precio"})),
    ("stock", frozenset({"stock", "cantidad", "unidades", "inv", "existencia"})),
    ("fecha_vencimiento", frozenset({"fecha_vencimiento", "vencimiento", "fecha_vto", "fecha"})),
]

_ALL_IMPORT_ALIASES: frozenset[str] = frozenset().union(*(a for _, a in _COLUMN_ALIAS_ORDER))


def _norm_encabezado_excel(cell) -> str:
    if cell is None:
        return ""
    s = str(cell).strip()
    if not s:
        return ""
    return _sin_acentos(s).lower().replace(" ", "_")


def _es_fila_encabezado_productos(cells: tuple) -> bool:
    """True si la fila parece títulos de columnas (no datos)."""
    hits = 0
    for c in cells:
        n = _norm_encabezado_excel(c)
        if n and n in _ALL_IMPORT_ALIASES:
            hits += 1
    return hits >= 2


def _construir_mapa_columnas_import(header_row: tuple) -> dict[str, int]:
    """Nombre lógico -> índice 0-based, según textos de la fila de encabezado."""
    colmap: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        n = _norm_encabezado_excel(cell)
        if not n:
            continue
        for key, aliases in _COLUMN_ALIAS_ORDER:
            if n in aliases and key not in colmap:
                colmap[key] = idx
                break
    return colmap


def _celda_import(row: tuple, key: str, colmap: dict[str, int] | None):
    # Si detectamos encabezados (colmap != None), usamos SOLO ese mapa.
    # Esto evita que, con encabezados parciales, se lean columnas equivocadas
    # (por ejemplo, que `stock` tome números de otra columna).
    if colmap is not None:
        if key not in colmap:
            return None
        i = colmap[key]
    else:
        i = _IMPORT_COL_FIXED[key]
    if len(row) <= i:
        return None
    return row[i]


def _parse_stock_importacion(v, fila_num: int) -> int:
    """
    Stock entero >= 0. No interpreta fechas ni números-serie de Excel como stock
    (evita cifras enormes si las columnas están desalineadas).
    """
    if v is None:
        return 0
    if isinstance(v, date):
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        fv = float(v)
        # Rango típico de serial de fecha (Excel): no usar como stock
        if 20000 < fv < 80000 and abs(fv - round(fv)) < 1e-9:
            return 0
    s = _celda_texto(v)
    if s == "":
        return 0
    try:
        n = int(_parse_decimal_celda(v, default=Decimal("0")))
    except ValueError as exc:
        raise ValueError(f"Fila {fila_num}: stock inválido ({s!r}).") from exc
    if n < 0:
        raise ValueError(f"Fila {fila_num}: el stock no puede ser negativo ({n}).")
    return n


IMPORT_EXCEL_CONFLICTS_KEY = "productos_import_excel_conflictos_v1"


def _tipo_label_producto(codigo_tipo: str) -> str:
    return dict(Producto.Tipo.choices).get(codigo_tipo, codigo_tipo)


def _excel_snapshot_for_session(
    defaults: dict,
    *,
    fecha_vencimiento: date | None,
) -> dict:
    """Valores serializables (JSON) para la sesión y para reaplicar si el usuario elige Excel."""
    snap: dict = {
        "descripcion": defaults["descripcion"],
        "tipo": defaults["tipo"],
        "tipo_label": _tipo_label_producto(defaults["tipo"]),
        "costo": str(defaults["costo"]),
        "stock": str(int(defaults["stock"])),
        "porcentaje_ganancia": str(defaults["porcentaje_ganancia"]),
        "fecha_vencimiento": fecha_vencimiento.isoformat() if fecha_vencimiento else "",
    }
    if defaults.get("precio_venta_editado"):
        snap["precio_venta"] = str(defaults["precio_venta"])
        snap["precio_automatico"] = False
    else:
        snap["precio_venta"] = ""
        snap["precio_automatico"] = True
    return snap


def _aplicar_snapshot_excel_a_producto(producto: Producto, snap: dict) -> None:
    producto.descripcion = (snap.get("descripcion") or "")[:255]
    producto.tipo = snap["tipo"]
    producto.costo = Decimal(snap["costo"])
    producto.stock = int(snap["stock"])
    producto.porcentaje_ganancia = Decimal(snap["porcentaje_ganancia"])
    fv = (snap.get("fecha_vencimiento") or "").strip()
    producto.fecha_vencimiento = date.fromisoformat(fv) if fv else None
    if snap.get("precio_automatico"):
        producto.precio_venta_editado = False
    else:
        producto.precio_venta = Decimal(snap["precio_venta"])
        producto.precio_venta_editado = True
    producto.save()


@login_required
def productos_list(request):
    productos, filtros_ctx = _filtrar_productos_queryset(request)
    q = filtros_ctx["q"]
    tipo = filtros_ctx["tipo"]
    proveedor = filtros_ctx["proveedor"]

    exp = parse_export(request)
    if exp in ("xlsx", "pdf"):
        headers = [
            "Código",
            "Descripción",
            "Tipo",
            "Costo",
            "Stock",
            "% ganancia",
            "Precio venta",
            "Habilitado",
            "Lista precios",
            "Fecha vencimiento",
        ]
        rows = []
        for p in productos:
            rows.append(
                [
                    p.codigo,
                    p.descripcion,
                    p.get_tipo_display(),
                    str(p.costo),
                    p.stock,
                    str(p.porcentaje_ganancia),
                    str(p.precio_venta),
                    "Sí" if p.habilitado else "No",
                    "Sí" if p.en_lista_precios else "No",
                    p.fecha_vencimiento.strftime("%d/%m/%Y") if p.fecha_vencimiento else "",
                ]
            )
        base = "productos"
        if exp == "xlsx":
            return xlsx_response(base, [("Productos", headers, rows)])
        return pdf_response(base, "Listado de productos", [("Productos", headers, rows)])

    listas = ListaPrecios.objects.all()
    proveedores_filtro = Proveedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")

    return render(
        request,
        "productos/list.html",
        {
            "productos": productos,
            "q": q,
            "tipo": tipo,
            "proveedor": proveedor,
            "tipos": Producto.Tipo.choices,
            "proveedores_filtro": proveedores_filtro,
            "listas": listas,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def productos_aumento(request):
    proveedores_filtro = Proveedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")

    if request.method == "POST":
        step = (request.POST.get("step") or "").strip()
        if step == "confirm":
            pct = _parse_pct_aumento(request)
            ids = [int(x) for x in request.POST.getlist("producto_id") if str(x).isdigit()]
            if pct is None:
                messages.error(request, "El porcentaje de aumento no es válido.")
                return _redirect_productos_aumento_filtros(request)
            if not ids:
                messages.error(request, "No se recibieron productos para actualizar.")
                return _redirect_productos_aumento_filtros(request)

            for sid in ids:
                if _parse_precio_venta_input(request.POST.get(f"precio_{sid}") or "") is None:
                    messages.error(
                        request,
                        f"Revisá el precio final del producto #{sid} (debe ser un importe válido).",
                    )
                    return _redirect_productos_aumento_filtros(request)

            factor = Decimal("1.0") + (pct / Decimal("100"))
            actualizados = 0
            try:
                with transaction.atomic():
                    for sid in ids:
                        precio = _parse_precio_venta_input(request.POST.get(f"precio_{sid}") or "")
                        p = Producto.objects.select_for_update().get(pk=sid)
                        p.costo = q2(p.costo * factor)
                        p.precio_venta = precio
                        p.precio_venta_editado = True
                        p.save()
                        actualizados += 1
            except Producto.DoesNotExist:
                messages.error(request, "Algún producto ya no existe.")
                return _redirect_productos_aumento_filtros(request)

            messages.success(
                request,
                f"Aumento del {pct}% aplicado sobre el costo en {actualizados} producto(s).",
            )
            return redirect("productos_list")

        if step == "preview":
            ids = [int(x) for x in request.POST.getlist("sel") if str(x).isdigit()]
            pct = _parse_pct_aumento(request)
            if not ids:
                messages.error(request, "Seleccioná al menos un producto.")
                return _redirect_productos_aumento_filtros(request)
            if pct is None:
                messages.error(request, "Indicá un porcentaje de aumento válido (ej.: 10 para 10%).")
                return _redirect_productos_aumento_filtros(request)

            factor = Decimal("1.0") + (pct / Decimal("100"))
            productos_sel = (
                Producto.objects.filter(pk__in=ids).order_by("descripcion", "codigo")
            )
            rows = []
            for p in productos_sel:
                nuevo_costo = q2(p.costo * factor)
                sugerido = q2(
                    nuevo_costo
                    * (Decimal("1.0") + (p.porcentaje_ganancia / Decimal("100")))
                )
                rows.append(
                    {
                        "producto": p,
                        "costo_anterior": p.costo,
                        "nuevo_costo": nuevo_costo,
                        "precio_sugerido": sugerido,
                    }
                )

            fq = (request.POST.get("filtro_q") or "").strip()
            ft = (request.POST.get("filtro_tipo") or "").strip()
            fp = (request.POST.get("filtro_proveedor") or "").strip()
            back_q = {}
            if fq:
                back_q["q"] = fq
            if ft:
                back_q["tipo"] = ft
            if fp:
                back_q["proveedor"] = fp
            aumento_back_url = reverse("productos_aumento")
            if back_q:
                aumento_back_url += "?" + urlencode(back_q)

            return render(
                request,
                "productos/aumento.html",
                {
                    "step": "confirm",
                    "pct": pct,
                    "rows": rows,
                    "filtro_q": fq,
                    "filtro_tipo": ft,
                    "filtro_proveedor": fp,
                    "aumento_back_url": aumento_back_url,
                    "proveedores_filtro": proveedores_filtro,
                },
            )

    productos, filtros_ctx = _filtrar_productos_queryset(request)
    return render(
        request,
        "productos/aumento.html",
        {
            "step": "filter",
            "productos": productos,
            "q": filtros_ctx["q"],
            "tipo": filtros_ctx["tipo"],
            "proveedor": filtros_ctx["proveedor"],
            "tipos": Producto.Tipo.choices,
            "proveedores_filtro": proveedores_filtro,
        },
    )


@login_required
@require_http_methods(["POST"])
def lista_precios_guardar(request):
    nombre = (request.POST.get("nombre") or "").strip()
    if not nombre:
        messages.error(request, "Tenés que ingresar un nombre para guardar la lista.")
        return redirect("productos_list")

    seleccion = list(Producto.objects.filter(en_lista_precios=True, habilitado=True).values_list("id", flat=True))
    if not seleccion:
        messages.error(request, "No hay productos seleccionados para guardar.")
        return redirect("productos_list")

    with transaction.atomic():
        lista, _created = ListaPrecios.objects.get_or_create(nombre=nombre)
        lista.productos.set(seleccion)

    messages.success(request, f"Lista guardada: {nombre}")
    return redirect("productos_list")


@login_required
@require_http_methods(["POST"])
def lista_precios_aplicar(request):
    lista_id = request.POST.get("lista_id")
    if not lista_id:
        messages.error(request, "Seleccioná una lista para aplicar.")
        return redirect("productos_list")

    lista = get_object_or_404(ListaPrecios, pk=lista_id)
    ids = list(lista.productos.values_list("id", flat=True))

    with transaction.atomic():
        Producto.objects.update(en_lista_precios=False)
        if ids:
            Producto.objects.filter(id__in=ids, habilitado=True).update(en_lista_precios=True)

    messages.success(request, f"Lista aplicada: {lista.nombre}")
    return redirect("productos_list")


def _render_producto_form(request, *, template_full: str, modo: str, form, producto=None):
    ctx = {
        "form": form,
        "modo": modo,
        "producto": producto,
        "form_action_url": (
            reverse("producto_update", args=[producto.pk])
            if producto
            else reverse("producto_create")
        ),
        "modal_title": (
            f"Editar · {producto.codigo}" if producto else "Nuevo producto"
        ),
    }
    if request.GET.get("modal") == "1":
        return render(request, "productos/form_fragment.html", ctx)
    return render(request, template_full, ctx)


@login_required
@require_http_methods(["GET", "POST"])
def producto_create(request):
    if request.method == "POST":
        form = ProductoForm(request.POST)
        if form.is_valid():
            producto = form.save(commit=False)
            producto.precio_venta_editado = bool(form.cleaned_data.get("precio_venta_editado"))
            producto.save()
            messages.success(request, f"Producto creado: {producto.codigo}")
            return redirect("productos_list")
    else:
        form = ProductoForm()
    return _render_producto_form(request, template_full="productos/form.html", modo="nuevo", form=form)


@login_required
@require_http_methods(["GET", "POST"])
def producto_update(request, pk: int):
    producto = get_object_or_404(Producto, pk=pk)
    if request.method == "POST":
        form = ProductoForm(request.POST, instance=producto)
        if form.is_valid():
            producto = form.save(commit=False)
            producto.precio_venta_editado = bool(form.cleaned_data.get("precio_venta_editado"))
            producto.save()
            messages.success(request, f"Producto actualizado: {producto.codigo}")
            return redirect("productos_list")
    else:
        form = ProductoForm(instance=producto)
    return _render_producto_form(
        request,
        template_full="productos/form.html",
        modo="editar",
        form=form,
        producto=producto,
    )


@login_required
@require_http_methods(["POST"])
def producto_delete(request, pk: int):
    producto = get_object_or_404(Producto, pk=pk)
    codigo = producto.codigo
    producto.delete()
    messages.success(request, f"Producto eliminado: {codigo}")
    return redirect("productos_list")


@login_required
@require_http_methods(["POST"])
def producto_toggle_habilitado(request, pk: int):
    producto = get_object_or_404(Producto, pk=pk)
    if not producto.habilitado and producto.stock <= 0:
        messages.warning(request, "No se puede habilitar un producto sin stock.")
        return redirect("productos_list")
    producto.habilitado = not producto.habilitado
    if not producto.habilitado:
        producto.en_lista_precios = False
    producto.save()
    return redirect("productos_list")


@login_required
@require_http_methods(["POST"])
def producto_toggle_lista(request, pk: int):
    producto = get_object_or_404(Producto, pk=pk)
    if not producto.habilitado:
        messages.warning(request, "No podés poner en lista un producto deshabilitado.")
        return redirect("productos_list")
    producto.en_lista_precios = request.POST.get("set_lista") == "1"
    producto.save(update_fields=["en_lista_precios"])
    return redirect("productos_list")


@login_required
@require_http_methods(["POST"])
def productos_acciones_masa(request):
    """Habilitar / deshabilitar / lista PDF sobre varios productos seleccionados."""
    accion = (request.POST.get("accion") or "").strip()
    ids = sorted({int(x) for x in request.POST.getlist("producto_id") if str(x).isdigit()})
    if not ids:
        messages.warning(request, "Seleccioná al menos un producto.")
        return _redirect_productos_con_filtros(request)

    existentes = set(Producto.objects.filter(pk__in=ids).values_list("pk", flat=True))
    ids = [i for i in ids if i in existentes]
    if not ids:
        messages.error(request, "No se encontraron productos válidos para la acción.")
        return _redirect_productos_con_filtros(request)

    if accion == "habilitar":
        sin_stock = Producto.objects.filter(pk__in=ids, habilitado=False, stock__lte=0).count()
        n = Producto.objects.filter(pk__in=ids, habilitado=False, stock__gt=0).update(habilitado=True)
        if n:
            messages.success(request, f"Se habilitaron {n} producto(s).")
        if sin_stock:
            messages.warning(
                request,
                f"No se habilitaron {sin_stock} producto(s) sin stock (o revisá el stock antes).",
            )
        if not n and not sin_stock:
            messages.info(request, "Los productos elegidos ya estaban habilitados.")
    elif accion == "deshabilitar":
        n = Producto.objects.filter(pk__in=ids).update(habilitado=False, en_lista_precios=False)
        messages.success(request, f"Se deshabilitaron {n} producto(s) y se sacaron de la lista PDF.")
    elif accion == "lista_si":
        deshab = Producto.objects.filter(pk__in=ids, habilitado=False).count()
        n = Producto.objects.filter(pk__in=ids, habilitado=True).update(en_lista_precios=True)
        messages.success(request, f"{n} producto(s) marcados para la lista de precios PDF.")
        if deshab:
            messages.info(
                request,
                f"{deshab} producto(s) deshabilitados no se incluyen en lista hasta habilitarlos.",
            )
    elif accion == "lista_no":
        n = Producto.objects.filter(pk__in=ids).update(en_lista_precios=False)
        messages.success(request, f"Se quitó la marca de lista PDF en {n} producto(s).")
    else:
        messages.error(request, "Acción no reconocida.")

    return _redirect_productos_con_filtros(request)


@login_required
@require_http_methods(["GET", "POST"])
def productos_import_excel(request):
    if request.method == "GET":
        return render(request, "productos/import_excel.html")

    f = request.FILES.get("archivo")
    if not f:
        return HttpResponseBadRequest("Falta archivo.")

    name = (getattr(f, "name", "") or "").lower()
    if not name.endswith(".xlsx"):
        messages.error(
            request,
            "El archivo debe ser Excel en formato .xlsx (Excel 2007 o posterior). "
            "Si tenés .xls, abrilo en Excel y guardalo como .xlsx.",
        )
        return redirect("productos_import_excel")

    try:
        raw = f.read()
        if not raw:
            messages.error(request, "El archivo está vacío.")
            return redirect("productos_import_excel")
        wb = load_workbook(filename=BytesIO(raw), data_only=True)
    except Exception as exc:
        messages.error(
            request,
            f"No se pudo leer el archivo. Comprobá que sea un .xlsx válido. Detalle: {exc}",
        )
        return redirect("productos_import_excel")

    ws = wb.active

    row1 = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    colmap: dict[str, int] | None = None
    data_start_row = 1
    if row1 and _es_fila_encabezado_productos(row1):
        colmap = _construir_mapa_columnas_import(row1)
        data_start_row = 2

    # Columnas: codigo(opcional), descripcion, tipo, costo, porcentaje_ganancia(opcional), precio_venta(opcional), stock(opcional), fecha_vencimiento(opcional)
    # Si la fila 1 tiene encabezados reconocidos, las columnas se ubican por título (orden libre).
    # Tipo: flexible — ver _resolver_tipo_producto
    #
    # Códigos que ya existen: no se pisan; se guardan en sesión y se muestran en un resumen para elegir.
    creados = 0
    conflictos: list[dict] = []

    try:
        with transaction.atomic():
            for i, row in enumerate(
                ws.iter_rows(min_row=data_start_row, values_only=True),
                start=data_start_row,
            ):
                if not row:
                    continue
                if all(v is None or _celda_texto(v) == "" for v in row):
                    continue

                codigo = _codigo_desde_celda(_celda_import(row, "codigo", colmap))
                descripcion = _celda_texto(_celda_import(row, "descripcion", colmap))
                tipo_raw = _celda_texto(_celda_import(row, "tipo", colmap))

                costo = _parse_decimal_celda(_celda_import(row, "costo", colmap), default=Decimal("0"))
                pct = _parse_decimal_celda(
                    _celda_import(row, "porcentaje_ganancia", colmap),
                    default=Decimal("30.00"),
                )
                precio = _parse_opcional_decimal(_celda_import(row, "precio_venta", colmap))

                stock = _parse_stock_importacion(_celda_import(row, "stock", colmap), i)

                fecha_vencimiento = None
                fv_cell = _celda_import(row, "fecha_vencimiento", colmap)
                if fv_cell is not None and _celda_texto(fv_cell) != "":
                    v = fv_cell
                    if hasattr(v, "date") and hasattr(v, "hour"):
                        fecha_vencimiento = v.date()
                    elif isinstance(v, date) and not hasattr(v, "hour"):
                        fecha_vencimiento = v
                    else:
                        s = _celda_texto(v)
                        for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
                            try:
                                fecha_vencimiento = datetime.strptime(s, fmt).date()
                                break
                            except ValueError:
                                continue
                        if fecha_vencimiento is None:
                            raise ValueError(
                                f"Fila {i}: fecha de vencimiento no reconocida ({s!r}). "
                                "Usá dd/mm/aaaa o el formato de fecha del modelo."
                            )

                if not descripcion:
                    continue

                if not tipo_raw:
                    raise ValueError(
                        f"Fila {i}: la columna «tipo» está vacía (tercera columna: MED, AC u OT). "
                        "Revisá que la fila 1 tenga encabezados y los datos empiecen en la fila 2, "
                        "sin columnas desplazadas. Podés descargar el modelo desde esta pantalla."
                    )

                tipo = _resolver_tipo_producto(tipo_raw)
                if not tipo:
                    raise ValueError(
                        f"Fila {i}: tipo no reconocido ({tipo_raw!r}). "
                        "Ejemplos: medicamento(s), accesorio(s), otros; o MED, AC, OT."
                    )

                defaults = {
                    "descripcion": descripcion,
                    "tipo": tipo,
                    "costo": costo,
                    "stock": stock,
                    "fecha_vencimiento": fecha_vencimiento,
                    "porcentaje_ganancia": pct,
                }

                if precio is None:
                    defaults["precio_venta_editado"] = False
                else:
                    defaults["precio_venta"] = precio
                    defaults["precio_venta_editado"] = True

                if codigo:
                    if Producto.objects.filter(codigo=codigo).exists():
                        existente = Producto.objects.get(codigo=codigo)
                        conflictos.append(
                            {
                                "fila": i,
                                "codigo": codigo,
                                "producto_id": existente.pk,
                                "excel": _excel_snapshot_for_session(defaults, fecha_vencimiento=fecha_vencimiento),
                            }
                        )
                        continue
                    Producto.objects.update_or_create(codigo=codigo, defaults=defaults)
                    creados += 1
                else:
                    obj = Producto(**defaults)
                    obj.save()
                    creados += 1
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("productos_import_excel")

    if conflictos:
        request.session[IMPORT_EXCEL_CONFLICTS_KEY] = {"items": conflictos}
        request.session.modified = True
        messages.success(
            request,
            f"Se cargaron {creados} producto(s) nuevo(s). "
            f"Hay {len(conflictos)} fila(s) con código ya existente: revisá el resumen y elegí qué datos conservar.",
        )
        return redirect("productos_import_excel_resumen")

    messages.success(request, f"Importación OK. Productos nuevos cargados: {creados}.")
    return redirect("productos_list")


@login_required
@require_http_methods(["GET", "POST"])
def productos_import_excel_resumen(request):
    """Tras importar, permite elegir por cada código duplicado si se aplica la fila del Excel o se mantiene la base."""
    payload = request.session.get(IMPORT_EXCEL_CONFLICTS_KEY) or {}
    items = list(payload.get("items") or [])

    if request.method == "POST":
        if not items:
            messages.info(request, "No había decisiones pendientes.")
            return redirect("productos_import_excel")
        actualizados = 0
        for it in items:
            pid = it.get("producto_id")
            if not pid:
                continue
            choice = (request.POST.get(f"resolver_{pid}") or "mantener").strip().lower()
            if choice == "excel":
                try:
                    p = Producto.objects.get(pk=pid)
                except Producto.DoesNotExist:
                    continue
                _aplicar_snapshot_excel_a_producto(p, it["excel"])
                actualizados += 1
        request.session.pop(IMPORT_EXCEL_CONFLICTS_KEY, None)
        messages.success(
            request,
            f"Listo. Se actualizaron {actualizados} producto(s) con los datos del Excel. "
            "El resto se mantuvo como estaba en la base.",
        )
        return redirect("productos_list")

    if not items:
        messages.info(request, "No hay un resumen de importación pendiente. Volvé a importar un archivo si hace falta.")
        return redirect("productos_import_excel")

    ids = [x["producto_id"] for x in items if x.get("producto_id")]
    productos = {p.pk: p for p in Producto.objects.filter(pk__in=ids)}
    filas = []
    for it in items:
        pid = it.get("producto_id")
        filas.append({**it, "producto": productos.get(pid) if pid else None})

    return render(
        request,
        "productos/import_excel_resumen.html",
        {"filas": filas},
    )


@login_required
@require_http_methods(["GET"])
def productos_import_excel_modelo(request):
    headers = [
        "codigo",
        "descripcion",
        "tipo",
        "costo",
        "porcentaje_ganancia",
        "precio_venta",
        "stock",
        "fecha_vencimiento",
    ]
    ejemplo = [
        [
            "",
            "Paracetamol 500mg",
            "MED",
            "100.00",
            "30.00",
            "",
            "0",
            "31/12/26",
        ]
    ]
    return xlsx_response("modelo_import_productos", [("Productos", headers, ejemplo)])


@login_required
def productos_export_pdf(request):
    incluir_stock = request.GET.get("stock") == "1"
    productos = list(
        Producto.objects.filter(en_lista_precios=True, habilitado=True).order_by("descripcion", "codigo")
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    story = platypus_membrete("Lista de precios", doc.width, styles)

    headers = ["Código", "Descripción"]
    if incluir_stock:
        headers.append("Stock")
    headers.append("Precio")

    data = [headers]
    for p in productos:
        desc = p.descripcion
        if len(desc) > 100:
            desc = desc[:97] + "..."
        row = [p.codigo, desc]
        if incluir_stock:
            row.append(str(p.stock))
        row.append(format_monto_ars(p.precio_venta))
        data.append(row)

    if len(data) == 1:
        row = ["—", "—"]
        if incluir_stock:
            row.append("—")
        row.append("—")
        data.append(row)

    tw = doc.width
    if incluir_stock:
        col_w = [tw * 0.14, tw * 0.46, tw * 0.12, tw * 0.28]
    else:
        col_w = [tw * 0.16, tw * 0.54, tw * 0.30]

    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0097B2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f9fb")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 1), (0, -1), "LEFT"),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(t)
    doc.build(story)
    buffer.seek(0)
    fecha = timezone.localtime().strftime("%d-%m-%Y")
    filename = f"Lista_Precios_Sirona_{fecha}.pdf"
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=filename,
        content_type="application/pdf",
    )

