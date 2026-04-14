import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
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
    return render(request, "productos/form.html", {"form": form, "modo": "nuevo"})


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
    return render(
        request,
        "productos/form.html",
        {"form": form, "producto": producto, "modo": "editar"},
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
        messages.warning(request, "No podés agregar a la lista un producto deshabilitado.")
        return redirect("productos_list")
    producto.en_lista_precios = not producto.en_lista_precios
    producto.save()
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

    # Espera columnas: codigo(opcional), descripcion, tipo, costo, porcentaje_ganancia(opcional), precio_venta(opcional), stock(opcional), fecha_vencimiento(opcional)
    # Tipo acepta: Medicamentos/Accesorios/Otros (o MED/AC/OT)
    creados = 0
    actualizados = 0

    tipo_map = {
        "MEDICAMENTOS": Producto.Tipo.MEDICAMENTOS,
        "MED": Producto.Tipo.MEDICAMENTOS,
        "ME": Producto.Tipo.MEDICAMENTOS,
        "ACCESORIOS": Producto.Tipo.ACCESORIOS,
        "AC": Producto.Tipo.ACCESORIOS,
        "OTROS": Producto.Tipo.OTROS,
        "OT": Producto.Tipo.OTROS,
    }

    try:
        with transaction.atomic():
            for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                if not row:
                    continue
                if all(v is None or _celda_texto(v) == "" for v in row):
                    continue

                codigo = _codigo_desde_celda(row[0]) if len(row) > 0 else ""
                descripcion = _celda_texto(row[1]) if len(row) > 1 else ""
                tipo_raw = _celda_texto(row[2]) if len(row) > 2 else ""

                costo = _parse_decimal_celda(
                    row[3] if len(row) > 3 else None, default=Decimal("0")
                )
                pct = (
                    _parse_decimal_celda(row[4], default=Decimal("30.00"))
                    if len(row) > 4
                    else Decimal("30.00")
                )
                precio = (
                    _parse_opcional_decimal(row[5]) if len(row) > 5 else None
                )
                stock = 0
                if len(row) > 6 and _celda_texto(row[6]) != "":
                    try:
                        stock = int(_parse_decimal_celda(row[6], default=Decimal("0")))
                    except ValueError:
                        raise ValueError(
                            f"Fila {i}: stock debe ser un número entero (recibido: {_celda_texto(row[6])!r})."
                        ) from None

                fecha_vencimiento = None
                if len(row) > 7 and _celda_texto(row[7]) != "":
                    v = row[7]
                    if hasattr(v, "date") and hasattr(v, "hour"):
                        fecha_vencimiento = v.date()
                    elif hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day"):
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

                tipo = tipo_map.get(tipo_raw.upper())
                if not tipo:
                    raise ValueError(
                        f"Fila {i}: tipo no reconocido ({tipo_raw!r}). "
                        "Usá Medicamentos, Accesorios, Otros o MED, AC, OT."
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
    return FileResponse(buffer, as_attachment=True, filename="lista_precios.pdf")

