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

from core.export_utils import parse_export, pdf_response, xlsx_response
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .forms import ProductoForm
from .models import ListaPrecios, Producto


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
    if colmap and key in colmap:
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


@login_required
def productos_list(request):
    q = (request.GET.get("q") or "").strip()
    tipo = (request.GET.get("tipo") or "").strip()

    productos = Producto.objects.all()
    if q:
        productos = productos.filter(Q(descripcion__icontains=q) | Q(codigo__icontains=q))
    if tipo:
        productos = productos.filter(tipo=tipo)

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
        for p in productos.order_by("codigo"):
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

    return render(
        request,
        "productos/list.html",
        {
            "productos": productos,
            "q": q,
            "tipo": tipo,
            "tipos": Producto.Tipo.choices,
            "listas": listas,
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
    creados = 0
    actualizados = 0

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
                    _obj, created = Producto.objects.update_or_create(
                        codigo=codigo, defaults=defaults
                    )
                else:
                    obj = Producto(**defaults)
                    obj.save()
                    created = True

                if created:
                    creados += 1
                else:
                    actualizados += 1
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("productos_import_excel")

    messages.success(request, f"Importación OK. Creados: {creados}. Actualizados: {actualizados}.")
    return redirect("productos_list")


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
    productos = (
        Producto.objects.filter(en_lista_precios=True, habilitado=True)
        .order_by("tipo", "descripcion", "codigo")
        .all()
    )

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 18 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(18 * mm, y, "Lista de precios")
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    c.drawString(18 * mm, y, "Código")
    c.drawString(38 * mm, y, "Descripción")
    if incluir_stock:
        c.drawRightString(width - 38 * mm, y, "Stock")
    c.drawRightString(width - 18 * mm, y, "Precio")
    y -= 6 * mm
    c.line(18 * mm, y, width - 18 * mm, y)
    y -= 6 * mm

    c.setFont("Helvetica", 10)
    for p in productos:
        if y < 20 * mm:
            c.showPage()
            y = height - 18 * mm
            c.setFont("Helvetica-Bold", 14)
            c.drawString(18 * mm, y, "Lista de precios")
            y -= 16 * mm
            c.setFont("Helvetica", 10)

        c.drawString(18 * mm, y, p.codigo)
        desc = p.descripcion
        if len(desc) > 60:
            desc = desc[:57] + "..."
        c.drawString(38 * mm, y, desc)
        if incluir_stock:
            c.drawRightString(width - 38 * mm, y, str(p.stock))
        c.drawRightString(width - 18 * mm, y, f"$ {p.precio_venta:.2f}")
        y -= 6 * mm

    c.showPage()
    c.save()
    buffer.seek(0)
    fecha = timezone.localdate().strftime("%Y-%m-%d")
    filename = f"Lista_Precios_Sirona_{fecha}.pdf"
    return FileResponse(buffer, as_attachment=True, filename=filename)

