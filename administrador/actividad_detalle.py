"""Arma el texto del historial con vendedor, cliente, monto e ítems."""

from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import urlparse

from django.utils import timezone

from .actividad import _norm_path, describir_actividad

_ID_RE = re.compile(
    r"^/(?P<sec>ventas|presupuestos|productos|compras|caja|bancos/gastos|"
    r"personas/vendedores|personas/proveedores|personas/compradores|"
    r"vendedor/presupuesto|vendedor/clientes)"
    r"/(?:admin/)?(?P<id>\d+)"
)
_LOC_PRESU = re.compile(r"/presupuestos/(\d+)")
_LOC_VENTA = re.compile(r"/ventas/(\d+)")


def _ok(response) -> bool:
    return getattr(response, "status_code", 0) in {200, 201, 204, 302, 303}


def _es_redirect(response) -> bool:
    return getattr(response, "status_code", 0) in {302, 303}


def _persona(obj) -> str:
    if obj is None:
        return ""
    ape = (getattr(obj, "apellido", None) or "").strip()
    nom = (getattr(obj, "nombre", None) or "").strip()
    if ape and nom:
        return f"{ape}, {nom}"
    return str(obj)


def _monto(valor) -> str:
    from core.money_decimal import format_monto_ars

    try:
        return format_monto_ars(valor)
    except Exception:
        return ""


def _items_de_lineas(lineas, *, limite: int = 3) -> str:
    nombres: list[str] = []
    total = 0
    for ln in lineas:
        total += 1
        if len(nombres) >= limite:
            continue
        prod = getattr(ln, "producto", None)
        desc = (
            (getattr(ln, "descripcion_snapshot", None) or "").strip()
            or (getattr(prod, "descripcion", None) or "").strip()
            or (getattr(ln, "codigo_snapshot", None) or "").strip()
            or (getattr(prod, "codigo", None) or "").strip()
        )
        qty = getattr(ln, "cantidad", None)
        if desc:
            nombres.append(f"{qty}× {desc[:42]}" if qty else desc[:42])
    if not nombres:
        return f"{total} producto(s)" if total else ""
    extra = total - len(nombres)
    if extra > 0:
        nombres.append(f"+{extra}")
    return ", ".join(nombres)


def _join(*partes: str) -> str:
    return " · ".join(p for p in partes if (p or "").strip())


def _dict_doc(kind: str, obj) -> dict:
    vendedor = _persona(getattr(obj, "vendedor", None))
    comprador = _persona(getattr(obj, "comprador", None))
    neto = _monto(getattr(obj, "neto", None))
    lineas = list(getattr(obj, "lineas", []).all()) if hasattr(getattr(obj, "lineas", None), "all") else []
    return {
        "kind": kind,
        "id": obj.pk,
        "vendedor": vendedor,
        "comprador": comprador or "sin cliente",
        "neto": neto,
        "items": _items_de_lineas(lineas),
        "n_items": len(lineas),
    }


def _texto_doc(verbo: str, data: dict, *, extra: str = "") -> str:
    kind = data.get("kind") or ""
    nid = data.get("id")
    etiqueta = "pedido" if kind == "venta" else kind
    cabeza = f"{verbo} {etiqueta} #{nid}" if nid else verbo
    return _join(
        cabeza,
        extra,
        data.get("vendedor") or "",
        data.get("comprador") or "",
        data.get("neto") or "",
        data.get("items") or "",
    )


def snapshot_para_request(request) -> dict | None:
    """Foto del registro antes de que un POST lo borre o cambie."""
    if (request.method or "").upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    path = _norm_path(request.path)
    m = _ID_RE.match(path)
    if not m:
        return None
    sec, pk = m.group("sec"), int(m.group("id"))
    try:
        if sec == "ventas" and "/despachos" not in path:
            from ventas.models import Venta

            obj = (
                Venta.objects.select_related("vendedor", "comprador")
                .prefetch_related("lineas__producto")
                .filter(pk=pk)
                .first()
            )
            return _dict_doc("venta", obj) if obj else None
        if sec == "presupuestos":
            from presupuestos.models import Presupuesto

            obj = (
                Presupuesto.objects.select_related("vendedor", "comprador")
                .prefetch_related("lineas__producto")
                .filter(pk=pk)
                .first()
            )
            return _dict_doc("presupuesto", obj) if obj else None
        if sec == "vendedor/presupuesto":
            from presupuestos.models import Presupuesto

            obj = (
                Presupuesto.objects.select_related("vendedor", "comprador")
                .prefetch_related("lineas__producto")
                .filter(pk=pk)
                .first()
            )
            return _dict_doc("presupuesto", obj) if obj else None
        if sec == "productos":
            from productos.models import Producto

            p = Producto.objects.filter(pk=pk).first()
            if not p:
                return None
            return {
                "kind": "producto",
                "id": p.pk,
                "nombre": f"{p.codigo} — {p.descripcion}"[:80],
            }
        if sec == "compras":
            from compras.models import Compra

            c = Compra.objects.select_related("proveedor", "producto").filter(pk=pk).first()
            if not c:
                return None
            return {
                "kind": "compra",
                "id": c.pk,
                "nombre": str(c.proveedor),
                "neto": _monto(c.monto),
                "items": (getattr(c.producto, "descripcion", "") or "")[:50],
            }
        if sec == "personas/vendedores":
            from personas.models import Vendedor

            o = Vendedor.objects.filter(pk=pk).first()
            return {"kind": "vendedor", "id": pk, "nombre": _persona(o)} if o else None
        if sec == "personas/proveedores":
            from personas.models import Proveedor

            o = Proveedor.objects.filter(pk=pk).first()
            return {"kind": "proveedor", "id": pk, "nombre": _persona(o)} if o else None
        if sec == "personas/compradores" or sec == "vendedor/clientes":
            from personas.models import Comprador

            o = Comprador.objects.filter(pk=pk).first()
            return {"kind": "cliente", "id": pk, "nombre": _persona(o)} if o else None
        if sec == "caja":
            from caja.models import MovimientoCaja

            o = MovimientoCaja.objects.filter(pk=pk).first()
            if not o:
                return None
            return {"kind": "caja", "id": pk, "neto": _monto(getattr(o, "monto", None)), "nombre": str(o)[:60]}
        if sec == "bancos/gastos":
            from bancos.models import Gasto

            o = Gasto.objects.filter(pk=pk).first()
            if not o:
                return None
            return {
                "kind": "gasto",
                "id": pk,
                "nombre": (getattr(o, "descripcion", "") or "")[:60],
                "neto": _monto(getattr(o, "monto", None)),
            }
    except Exception:
        return None
    return None


def _location_path(response) -> str:
    loc = (getattr(response, "headers", None) or {}).get("Location") or ""
    if not loc and hasattr(response, "get"):
        loc = response.get("Location") or ""
    if not loc:
        return ""
    return _norm_path(urlparse(loc).path or loc)


def _id_en_location(response, rx: re.Pattern[str]) -> int | None:
    m = rx.search(_location_path(response))
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _cargar_venta(pk: int) -> dict | None:
    from ventas.models import Venta

    obj = (
        Venta.objects.select_related("vendedor", "comprador")
        .prefetch_related("lineas__producto")
        .filter(pk=pk)
        .first()
    )
    return _dict_doc("venta", obj) if obj else None


def _cargar_presupuesto(pk: int) -> dict | None:
    from presupuestos.models import Presupuesto

    obj = (
        Presupuesto.objects.select_related("vendedor", "comprador")
        .prefetch_related("lineas__producto")
        .filter(pk=pk)
        .first()
    )
    return _dict_doc("presupuesto", obj) if obj else None


def _ultimo_del_usuario(model, user, *, segundos: int = 20):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    desde = timezone.now() - timedelta(seconds=segundos)
    return (
        model.objects.filter(creado_por=user, creado_en__gte=desde)
        .select_related("vendedor", "comprador")
        .prefetch_related("lineas__producto")
        .order_by("-id")
        .first()
    )


def _n_lineas_post(request) -> int:
    return len([p for p in request.POST.getlist("linea_producto") if (p or "").strip()])


def descripcion_detallada(request, response) -> str:
    """Texto para guardar: acción + datos del documento si el POST tuvo efecto."""
    method = request.method or "?"
    path = _norm_path(request.path)
    consulta = (request.META.get("QUERY_STRING") or "")[:512]
    base = describir_actividad(method, path, consulta, "").texto
    if not _ok(response):
        return base
    if (method or "").upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return base

    snap = getattr(request, "_sirona_act_snap", None) or {}
    try:
        detalle = _armar_detalle(request, response, path, snap)
    except Exception:
        detalle = ""
    return (detalle or base)[:500]


def _armar_detalle(request, response, path: str, snap: dict) -> str:
    redir = _es_redirect(response)

    if path == "/ventas/nueva":
        if redir:
            from ventas.models import Venta

            obj = _ultimo_del_usuario(Venta, request.user)
            data = _dict_doc("venta", obj) if obj else None
            if data:
                return _texto_doc("Creó", data)
            return "Creó un pedido"
        return "Intentó crear un pedido (no se guardó)"

    if path in {"/presupuestos/nuevo", "/vendedor"}:
        if redir:
            from presupuestos.models import Presupuesto

            obj = _ultimo_del_usuario(Presupuesto, request.user)
            data = _dict_doc("presupuesto", obj) if obj else None
            if data:
                origen = "desde el portal" if path == "/vendedor" else ""
                return _texto_doc("Creó", data, extra=origen)
            if path == "/presupuestos/nuevo":
                return "Creó un presupuesto"
        elif path == "/presupuestos/nuevo":
            return "Intentó crear un presupuesto (no se guardó)"

    m_dup = re.match(r"^/presupuestos/(\d+)/duplicar$", path)
    if m_dup:
        orig = snap if snap.get("kind") == "presupuesto" else _cargar_presupuesto(int(m_dup.group(1)))
        nuevo_id = _id_en_location(response, _LOC_PRESU)
        data = _cargar_presupuesto(nuevo_id) if nuevo_id else orig
        if data or orig:
            src = orig or data or {}
            src_id = src.get("id")
            if src_id and nuevo_id and int(nuevo_id) != int(src_id):
                cabeza = f"Duplicó presupuesto #{src_id} a #{nuevo_id}"
            elif src_id:
                cabeza = f"Duplicó presupuesto #{src_id}"
            else:
                cabeza = "Duplicó un presupuesto"
            cuerpo = data or src
            return _join(
                cabeza,
                cuerpo.get("vendedor") or "",
                cuerpo.get("comprador") or "",
                cuerpo.get("neto") or "",
                cuerpo.get("items") or "",
            )

    m_apr = re.match(r"^/presupuestos/(\d+)/aprobar$", path)
    if m_apr and redir:
        from presupuestos.models import Presupuesto

        pr = (
            Presupuesto.objects.select_related("vendedor", "comprador", "venta")
            .prefetch_related("lineas__producto")
            .filter(pk=int(m_apr.group(1)))
            .first()
        )
        if pr:
            data = _dict_doc("presupuesto", pr)
            extra = f"generó pedido #{pr.venta_id}" if pr.venta_id else "generó un pedido"
            return _texto_doc("Aprobó", data, extra=extra)

    m_el_pr = re.match(r"^/presupuestos/(\d+)/eliminar$", path) or re.match(
        r"^/vendedor/presupuesto/(\d+)/eliminar$", path
    )
    if m_el_pr:
        data = snap if snap.get("kind") == "presupuesto" else None
        if data:
            return _texto_doc("Eliminó", data)

    m_ed_pr = re.match(r"^/presupuestos/(\d+)/editar$", path)
    if m_ed_pr and redir:
        data = _cargar_presupuesto(int(m_ed_pr.group(1))) or (snap if snap.get("kind") == "presupuesto" else None)
        if data:
            return _texto_doc("Editó", data)

    m_el_ve = re.match(r"^/ventas/(\d+)/eliminar$", path)
    if m_el_ve:
        data = snap if snap.get("kind") == "venta" else None
        if data:
            return _texto_doc("Eliminó", data)

    m_ed_ve = re.match(r"^/ventas/(\d+)/editar$", path)
    if m_ed_ve and redir:
        data = _cargar_venta(int(m_ed_ve.group(1))) or (snap if snap.get("kind") == "venta" else None)
        if data:
            return _texto_doc("Editó", data)

    m_pago = re.match(r"^/ventas/(\d+)/pago$", path)
    if m_pago and redir:
        data = _cargar_venta(int(m_pago.group(1))) or (snap if snap.get("kind") == "venta" else None)
        medio = (request.POST.get("medio_pago") or "").strip()
        extra = f"medio {medio}" if medio else ""
        if data:
            return _texto_doc("Registró cobro de", data, extra=extra)
        return _join(f"Registró cobro de pedido #{m_pago.group(1)}", extra)

    if path == "/ventas/pago-masivo" and redir:
        ids = [x for x in request.POST.getlist("venta_id") if str(x).isdigit()]
        return f"Registró cobro de {len(ids)} pedido(s)" if ids else "Registró cobro de varios pedidos"

    m_prod_del = re.match(r"^/productos/(\d+)/eliminar$", path)
    if m_prod_del:
        nombre = (snap or {}).get("nombre") or f"#{m_prod_del.group(1)}"
        return f"Eliminó producto {nombre}"

    m_prod_ed = re.match(r"^/productos/(\d+)/editar$", path)
    if m_prod_ed and redir:
        nombre = (snap or {}).get("nombre") or f"#{m_prod_ed.group(1)}"
        return f"Editó producto {nombre}"

    if path == "/productos/nuevo" and redir:
        desc = (request.POST.get("descripcion") or "").strip()
        codigo = (request.POST.get("codigo") or "").strip()
        return _join("Creó un producto", f"{codigo} {desc}".strip())

    m_comp = re.match(r"^/compras/admin/(\d+)/(eliminar|anular)$", path)
    if m_comp:
        verbo = "Eliminó" if m_comp.group(2) == "eliminar" else "Anuló"
        return _join(
            f"{verbo} compra #{(snap or {}).get('id') or m_comp.group(1)}",
            (snap or {}).get("nombre") or "",
            (snap or {}).get("neto") or "",
            (snap or {}).get("items") or "",
        )

    if path == "/compras/nueva" and redir:
        return _join(
            "Registró una compra",
            (request.POST.get("nombre_producto") or "").strip()[:60],
            _monto(request.POST.get("monto") or request.POST.get("costo_unitario") or ""),
        )

    for kind, label, rx in (
        ("vendedor", "vendedor", r"^/personas/vendedores/(\d+)/(eliminar|eliminar-admin)$"),
        ("proveedor", "proveedor", r"^/personas/proveedores/(\d+)/eliminar$"),
        ("cliente", "cliente", r"^/personas/compradores/(\d+)/eliminar$"),
        ("cliente", "cliente", r"^/vendedor/clientes/(\d+)/eliminar$"),
        ("caja", "movimiento de caja", r"^/caja/(\d+)/eliminar$"),
        ("gasto", "gasto", r"^/bancos/gastos/(\d+)/eliminar$"),
    ):
        mm = re.match(rx, path)
        if mm:
            nombre = (snap or {}).get("nombre") or f"#{mm.group(1)}"
            extra = (snap or {}).get("neto") or ""
            return _join(f"Eliminó {label} {nombre}", extra)

    npost = _n_lineas_post(request)
    if npost and snap.get("kind") in {"venta", "presupuesto"} and redir:
        return _texto_doc("Guardó cambios en", snap)

    return ""
