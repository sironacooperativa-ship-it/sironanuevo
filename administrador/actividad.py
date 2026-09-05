"""Traduce peticiones HTTP a acciones legibles para el historial de usuarios."""

from __future__ import annotations

import re
from typing import NamedTuple


class AccionInfo(NamedTuple):
    texto: str
    grupo: str
    es_mutacion: bool


GRUPOS: list[tuple[str, str]] = [
    ("", "Todas las secciones"),
    ("sesion", "Sesión"),
    ("pedidos", "Pedidos"),
    ("despachos", "Despachos"),
    ("presupuestos", "Presupuestos"),
    ("productos", "Productos"),
    ("stock", "Stock"),
    ("caja", "Caja"),
    ("compras", "Compras"),
    ("personas", "Personas"),
    ("bancos", "Bancos"),
    ("calendario", "Calendario"),
    ("reportes", "Reportes"),
    ("mensajes", "Mensajes"),
    ("admin", "Administrador"),
    ("portal", "Portal vendedor"),
    ("inicio", "Inicio"),
]

# Prefijos de ruta para filtrar en SQL (el más específico primero).
_GRUPO_PREFIXES: list[tuple[str, str]] = [
    ("/ventas/despachos", "despachos"),
    ("/ventas", "pedidos"),
    ("/presupuestos", "presupuestos"),
    ("/productos", "productos"),
    ("/stock", "stock"),
    ("/caja", "caja"),
    ("/compras", "compras"),
    ("/personas", "personas"),
    ("/bancos", "bancos"),
    ("/calendario", "calendario"),
    ("/reportes", "reportes"),
    ("/administrador", "admin"),
    ("/notas", "mensajes"),
    ("/vendedor", "portal"),
    ("/login", "sesion"),
    ("/logout", "sesion"),
    ("/sesion", "sesion"),
    ("/modo-", "sesion"),
    ("/cuenta", "sesion"),
    ("/demo", "inicio"),
]


def _norm_path(path: str) -> str:
    p = (path or "").strip()
    if len(p) > 1:
        p = p.rstrip("/")
    return p or "/"


def _is_write(method: str) -> bool:
    return (method or "").upper() in {"POST", "PUT", "PATCH", "DELETE"}


def _fmt(plantilla: str, groups: dict[str, str]) -> str:
    try:
        return plantilla.format(**groups)
    except KeyError:
        return plantilla


def grupo_de_ruta(path: str) -> str:
    p = _norm_path(path)
    if p == "/":
        return "inicio"
    for prefix, grupo in _GRUPO_PREFIXES:
        if p == prefix.rstrip("/") or p.startswith(prefix):
            return grupo
    return ""


def q_grupo(grupo: str):
    """Filtro ORM por sección (ruta)."""
    from django.db.models import Q

    g = (grupo or "").strip()
    if not g:
        return Q()
    if g == "inicio":
        return Q(ruta="/") | Q(ruta="")
    if g == "sesion":
        return (
            Q(ruta__startswith="/login")
            | Q(ruta__startswith="/logout")
            | Q(ruta__startswith="/sesion")
            | Q(ruta__startswith="/modo-")
            | Q(ruta__startswith="/cuenta")
            | Q(descripcion__in=["Inicio de sesión", "Cierre de sesión"])
        )
    if g == "mensajes":
        return Q(ruta__startswith="/notas") | Q(ruta__contains="/notas/")
    if g == "despachos":
        return Q(ruta__startswith="/ventas/despachos")
    if g == "pedidos":
        return Q(ruta__startswith="/ventas") & ~Q(ruta__startswith="/ventas/despachos")
    prefixes = [pref for pref, name in _GRUPO_PREFIXES if name == g]
    if not prefixes:
        return Q()
    q = Q()
    for pref in prefixes:
        q |= Q(ruta__startswith=pref)
    return q


# (regex, grupo, texto GET, texto escritura). {id} y {id2} salen de grupos nombrados.
_REGLAS: list[tuple[str, str, str, str]] = [
    (r"^/login$", "sesion", "Inicio de sesión", "Inicio de sesión"),
    (r"^/logout$", "sesion", "Cierre de sesión", "Cierre de sesión"),
    (r"^/sesion/cerrar-al-cerrar-ventana$", "sesion", "Cierre de sesión (ventana)", "Cierre de sesión (ventana)"),
    (r"^/modo-vendedor$", "sesion", "Cambió a modo vendedor", "Cambió a modo vendedor"),
    (r"^/modo-completo$", "sesion", "Volvió a modo completo", "Volvió a modo completo"),
    (r"^/modo-admin$", "sesion", "Cambió a modo administrador", "Cambió a modo administrador"),
    (r"^/cuenta/contrasena$", "sesion", "Abrió cambio de contraseña", "Cambió su contraseña"),
    (r"^/$", "inicio", "Entró al inicio", "Entró al inicio"),
    (r"^/buscar\.json$", "inicio", "Usó la búsqueda global", "Usó la búsqueda global"),
    (r"^/notas/enviar$", "mensajes", "Abrió mensajes", "Envió un mensaje a administración"),
    (r"^/notas/chat\.json$", "mensajes", "Leyó mensajes", "Leyó mensajes"),
    (r"^/notas/marcar-leidas-usuario$", "mensajes", "Marcó mensajes como leídos", "Marcó mensajes como leídos"),
    # Pedidos
    (r"^/ventas$", "pedidos", "Vió historial de pedidos", "Vió historial de pedidos"),
    (r"^/ventas/nueva$", "pedidos", "Abrió nuevo pedido", "Creó un pedido"),
    (r"^/ventas/(?P<id>\d+)$", "pedidos", "Vió pedido #{id}", "Vió pedido #{id}"),
    (r"^/ventas/(?P<id>\d+)/editar$", "pedidos", "Abrió edición de pedido #{id}", "Editó pedido #{id}"),
    (r"^/ventas/(?P<id>\d+)/eliminar$", "pedidos", "Abrió baja de pedido #{id}", "Eliminó pedido #{id}"),
    (r"^/ventas/(?P<id>\d+)/pago$", "pedidos", "Abrió cobro de pedido #{id}", "Registró cobro de pedido #{id}"),
    (r"^/ventas/pago-masivo$", "pedidos", "Abrió cobro masivo", "Registró cobro de varios pedidos"),
    (r"^/ventas/(?P<id>\d+)/comision$", "pedidos", "Vió comisión de pedido #{id}", "Actualizó comisión de pedido #{id}"),
    (r"^/ventas/(?P<id>\d+)/despacho$", "pedidos", "Vió despacho de pedido #{id}", "Actualizó despacho de pedido #{id}"),
    (r"^/ventas/comisiones$", "pedidos", "Vió comisiones", "Liquidó comisiones"),
    (r"^/ventas/comisiones/historial$", "pedidos", "Vió historial de comisiones", "Vió historial de comisiones"),
    (r"^/ventas/comisiones/liquidacion-pagar$", "pedidos", "Abrió pago de liquidación", "Pagó liquidación de comisiones"),
    (r"^/ventas/comisiones/constancia/(?P<id>\d+)$", "pedidos", "Descargó constancia de comisión #{id}", "Descargó constancia de comisión #{id}"),
    (r"^/ventas/catalogo-precios$", "pedidos", "Consultó catálogo de precios", "Consultó catálogo de precios"),
    (r"^/ventas/catalogo-completo$", "pedidos", "Consultó catálogo completo", "Consultó catálogo completo"),
    (r"^/ventas/(?P<id>\d+)/producto/(?P<id2>\d+)/listas$", "pedidos", "Consultó listas del producto #{id2}", "Consultó listas del producto #{id2}"),
    # Despachos
    (r"^/ventas/despachos$", "despachos", "Vió despachos", "Vió despachos"),
    (r"^/ventas/despachos/historial$", "despachos", "Vió historial de despachos", "Vió historial de despachos"),
    (r"^/ventas/despachos/armado$", "despachos", "Vió armado de pedidos", "Vió armado de pedidos"),
    (r"^/ventas/despachos/armado/colectivo$", "despachos", "Abrió armado colectivo", "Armó pedidos en colectivo"),
    (r"^/ventas/despachos/armado/colectivo/guardar$", "despachos", "Abrió guardado de armado", "Guardó armado colectivo"),
    (r"^/ventas/despachos/armado/colectivo/pdf$", "despachos", "Descargó PDF de armado", "Descargó PDF de armado"),
    (r"^/ventas/despachos/armado/guardado/(?P<id>\d+)$", "despachos", "Vió armado #{id}", "Vió armado #{id}"),
    (r"^/ventas/despachos/armado/guardado/(?P<id>\d+)/editar$", "despachos", "Abrió edición de armado #{id}", "Editó armado #{id}"),
    (r"^/ventas/despachos/armado/guardado/(?P<id>\d+)/eliminar$", "despachos", "Abrió baja de armado #{id}", "Eliminó armado #{id}"),
    (r"^/ventas/despachos/armado/edicion/cancelar$", "despachos", "Canceló edición de armado", "Canceló edición de armado"),
    (r"^/ventas/despachos/armado/guardado/(?P<id>\d+)/despachar$", "despachos", "Abrió despacho de armado #{id}", "Marcó despachados del armado #{id}"),
    (r"^/ventas/despachos/armado/guardado/(?P<id>\d+)/pdf$", "despachos", "Descargó PDF de armado #{id}", "Descargó PDF de armado #{id}"),
    (r"^/ventas/despachos/puntos-stock$", "despachos", "Vió puntos de stock", "Vió puntos de stock"),
    (r"^/ventas/despachos/puntos-stock/guardar$", "despachos", "Abrió puntos de stock", "Guardó puntos de stock"),
    # Presupuestos
    (r"^/presupuestos$", "presupuestos", "Vió presupuestos", "Vió presupuestos"),
    (r"^/presupuestos/nuevo$", "presupuestos", "Abrió nuevo presupuesto", "Creó un presupuesto"),
    (r"^/presupuestos/(?P<id>\d+)$", "presupuestos", "Vió presupuesto #{id}", "Vió presupuesto #{id}"),
    (r"^/presupuestos/(?P<id>\d+)/editar$", "presupuestos", "Abrió edición de presupuesto #{id}", "Editó presupuesto #{id}"),
    (r"^/presupuestos/(?P<id>\d+)/eliminar$", "presupuestos", "Abrió baja de presupuesto #{id}", "Eliminó presupuesto #{id}"),
    (r"^/presupuestos/(?P<id>\d+)/aprobar$", "presupuestos", "Abrió aprobación de presupuesto #{id}", "Aprobó presupuesto #{id} (pasó a pedido)"),
    (r"^/presupuestos/aprobar-masivo$", "presupuestos", "Abrió aprobación masiva", "Aprobó varios presupuestos"),
    (r"^/presupuestos/(?P<id>\d+)/duplicar$", "presupuestos", "Abrió duplicado de presupuesto #{id}", "Duplicó presupuesto #{id}"),
    (r"^/presupuestos/(?P<id>\d+)/comparativa$", "presupuestos", "Vió comparativa de presupuesto #{id}", "Vió comparativa de presupuesto #{id}"),
    (r"^/presupuestos/(?P<id>\d+)/resolver-catalogo$", "presupuestos", "Resolvió catálogo de presupuesto #{id}", "Resolvió catálogo de presupuesto #{id}"),
    (r"^/presupuestos/catalogo-precios$", "presupuestos", "Consultó catálogo de presupuestos", "Consultó catálogo de presupuestos"),
    (r"^/presupuestos/c/(?P<id>[^/]+)$", "presupuestos", "Abrió presupuesto compartido", "Abrió presupuesto compartido"),
    # Productos
    (r"^/productos$", "productos", "Vió productos", "Vió productos"),
    (r"^/productos/nuevo$", "productos", "Abrió alta de producto", "Creó un producto"),
    (r"^/productos/(?P<id>\d+)/editar$", "productos", "Abrió edición de producto #{id}", "Editó producto #{id}"),
    (r"^/productos/(?P<id>\d+)/inline$", "productos", "Editó producto #{id} en lista", "Editó producto #{id} en lista"),
    (r"^/productos/(?P<id>\d+)/eliminar$", "productos", "Abrió baja de producto #{id}", "Eliminó producto #{id}"),
    (r"^/productos/(?P<id>\d+)/toggle-habilitado$", "productos", "Cambió habilitación de producto #{id}", "Cambió habilitación de producto #{id}"),
    (r"^/productos/(?P<id>\d+)/toggle-lista$", "productos", "Cambió lista de producto #{id}", "Cambió lista de producto #{id}"),
    (r"^/productos/acciones-masa$", "productos", "Abrió acciones masivas", "Aplicó acciones masivas a productos"),
    (r"^/productos/aumento$", "productos", "Abrió aumentos de precios", "Aplicó aumentos de precios"),
    (r"^/productos/vencimientos$", "productos", "Vió vencimientos de productos", "Vió vencimientos de productos"),
    (r"^/productos/importar-excel$", "productos", "Abrió importación de productos", "Importó productos desde Excel"),
    (r"^/productos/importar-excel/resumen$", "productos", "Vió resumen de importación", "Vió resumen de importación"),
    (r"^/productos/importar-excel/modelo\.xlsx$", "productos", "Descargó modelo de importación", "Descargó modelo de importación"),
    (r"^/productos/lista-precios\.pdf$", "productos", "Descargó lista de precios PDF", "Descargó lista de precios PDF"),
    (r"^/productos/export/costos\.xlsx$", "productos", "Exportó costos a Excel", "Exportó costos a Excel"),
    (r"^/productos/picker\.json$", "productos", "Buscó productos", "Buscó productos"),
    (r"^/productos/stock-cero-resolver$", "productos", "Resolvió stock en cero", "Resolvió stock en cero"),
    (r"^/productos/(?P<id>\d+)/listas-comparativa\.json$", "productos", "Consultó comparativa de listas #{id}", "Consultó comparativa de listas #{id}"),
    (r"^/productos/listas/guardar$", "productos", "Abrió guardado de lista", "Guardó lista de precios"),
    (r"^/productos/listas/aplicar$", "productos", "Abrió aplicación de lista", "Aplicó lista de precios"),
    (r"^/productos/listas-precio$", "productos", "Vió listas de precio", "Vió listas de precio"),
    (r"^/productos/listas-precio/nueva$", "productos", "Abrió nueva lista de precio", "Creó lista de precio"),
    (r"^/productos/listas-precio/nueva/confirmar$", "productos", "Confirmó nueva lista", "Confirmó nueva lista de precio"),
    (r"^/productos/listas-precio/(?P<id>\d+)$", "productos", "Trabajó lista de precio #{id}", "Guardó cambios en lista #{id}"),
    (r"^/productos/listas-precio/(?P<id>\d+)/ver$", "productos", "Vió lista de precio #{id}", "Vió lista de precio #{id}"),
    (r"^/productos/listas-precio/(?P<id>\d+)/renombrar$", "productos", "Abrió renombre de lista #{id}", "Renombró lista de precio #{id}"),
    (r"^/productos/listas-precio/(?P<id>\d+)/eliminar$", "productos", "Abrió baja de lista #{id}", "Eliminó lista de precio #{id}"),
    (r"^/productos/listas-precio/(?P<id>\d+)/export/pdf$", "productos", "Exportó lista #{id} a PDF", "Exportó lista #{id} a PDF"),
    (r"^/productos/listas-precio/(?P<id>\d+)/export/excel$", "productos", "Exportó lista #{id} a Excel", "Exportó lista #{id} a Excel"),
    (r"^/productos/listas-precio/(?P<id>\d+)/export/png$", "productos", "Exportó lista #{id} a imagen", "Exportó lista #{id} a imagen"),
    # Stock
    (r"^/stock$", "stock", "Vió stock", "Vió stock"),
    (r"^/stock/ajuste$", "stock", "Abrió ajuste de stock", "Ajustó stock"),
    (r"^/stock/quick-add/(?P<id>\d+)$", "stock", "Abrió carga rápida #{id}", "Sumó stock al producto #{id}"),
    # Caja
    (r"^/caja$", "caja", "Vió caja", "Vió caja"),
    (r"^/caja/historico$", "caja", "Vió histórico de caja", "Vió histórico de caja"),
    (r"^/caja/cheques$", "caja", "Vió cheques", "Vió cheques"),
    (r"^/caja/nuevo$", "caja", "Abrió movimiento de caja", "Cargó un movimiento de caja"),
    (r"^/caja/(?P<id>\d+)$", "caja", "Vió movimiento de caja #{id}", "Vió movimiento de caja #{id}"),
    (r"^/caja/(?P<id>\d+)/editar$", "caja", "Abrió edición de caja #{id}", "Editó movimiento de caja #{id}"),
    (r"^/caja/(?P<id>\d+)/eliminar$", "caja", "Abrió baja de caja #{id}", "Eliminó movimiento de caja #{id}"),
    # Compras
    (r"^/compras$", "compras", "Vió historial de compras", "Vió historial de compras"),
    (r"^/compras/nueva$", "compras", "Abrió nueva compra", "Registró una compra"),
    (r"^/compras/admin/(?P<id>\d+)/eliminar$", "compras", "Abrió baja de compra #{id}", "Eliminó compra #{id}"),
    (r"^/compras/admin/(?P<id>\d+)/anular$", "compras", "Abrió anulación de compra #{id}", "Anuló compra #{id}"),
    # Personas
    (r"^/personas/vendedores$", "personas", "Vió vendedores", "Vió vendedores"),
    (r"^/personas/vendedores/nuevo$", "personas", "Abrió alta de vendedor", "Creó un vendedor"),
    (r"^/personas/vendedores/(?P<id>\d+)$", "personas", "Vió ficha de vendedor #{id}", "Vió ficha de vendedor #{id}"),
    (r"^/personas/vendedores/(?P<id>\d+)/editar$", "personas", "Abrió edición de vendedor #{id}", "Editó vendedor #{id}"),
    (r"^/personas/vendedores/(?P<id>\d+)/eliminar$", "personas", "Abrió baja de vendedor #{id}", "Eliminó vendedor #{id}"),
    (r"^/personas/vendedores/(?P<id>\d+)/eliminar-admin$", "personas", "Abrió baja admin de vendedor #{id}", "Eliminó vendedor #{id} y su historial"),
    (r"^/personas/vendedores/(?P<id>\d+)/toggle$", "personas", "Cambió estado de vendedor #{id}", "Cambió estado de vendedor #{id}"),
    (r"^/personas/vendedores/(?P<id>\d+)/actividad$", "personas", "Vió actividad de vendedor #{id}", "Vió actividad de vendedor #{id}"),
    (r"^/personas/vendedores/(?P<id>\d+)/ficha$", "personas", "Vió ficha de vendedor #{id}", "Vió ficha de vendedor #{id}"),
    (r"^/personas/proveedores$", "personas", "Vió proveedores", "Vió proveedores"),
    (r"^/personas/proveedores/nuevo$", "personas", "Abrió alta de proveedor", "Creó un proveedor"),
    (r"^/personas/proveedores/(?P<id>\d+)/editar$", "personas", "Abrió edición de proveedor #{id}", "Editó proveedor #{id}"),
    (r"^/personas/proveedores/(?P<id>\d+)/eliminar$", "personas", "Abrió baja de proveedor #{id}", "Eliminó proveedor #{id}"),
    (r"^/personas/proveedores/(?P<id>\d+)/toggle$", "personas", "Cambió estado de proveedor #{id}", "Cambió estado de proveedor #{id}"),
    (r"^/personas/compradores$", "personas", "Vió clientes", "Vió clientes"),
    (r"^/personas/compradores/nuevo$", "personas", "Abrió alta de cliente", "Creó un cliente"),
    (r"^/personas/compradores/(?P<id>\d+)/editar$", "personas", "Abrió edición de cliente #{id}", "Editó cliente #{id}"),
    (r"^/personas/compradores/(?P<id>\d+)/eliminar$", "personas", "Abrió baja de cliente #{id}", "Eliminó cliente #{id}"),
    (r"^/personas/compradores/(?P<id>\d+)/toggle$", "personas", "Cambió estado de cliente #{id}", "Cambió estado de cliente #{id}"),
    (r"^/personas/compradores/(?P<id>\d+)/ficha$", "personas", "Vió ficha de cliente #{id}", "Vió ficha de cliente #{id}"),
    # Bancos
    (r"^/bancos$", "bancos", "Vió cuentas bancarias", "Vió cuentas bancarias"),
    (r"^/bancos/cuentas/nueva$", "bancos", "Abrió alta de cuenta", "Creó una cuenta bancaria"),
    (r"^/bancos/cuentas/(?P<id>\d+)$", "bancos", "Vió cuenta bancaria #{id}", "Vió cuenta bancaria #{id}"),
    (r"^/bancos/cuentas/(?P<id>\d+)/ajuste$", "bancos", "Abrió ajuste de cuenta #{id}", "Ajustó cuenta bancaria #{id}"),
    (r"^/bancos/gastos$", "bancos", "Vió gastos bancarios", "Vió gastos bancarios"),
    (r"^/bancos/gastos/nuevo$", "bancos", "Abrió nuevo gasto", "Cargó un gasto por transferencia"),
    (r"^/bancos/gastos/(?P<id>\d+)/eliminar$", "bancos", "Abrió baja de gasto #{id}", "Eliminó gasto #{id}"),
    # Calendario / reportes
    (r"^/calendario$", "calendario", "Vió calendario", "Cargó o editó un evento"),
    (r"^/calendario/exportar-pdf$", "calendario", "Exportó calendario a PDF", "Exportó calendario a PDF"),
    (r"^/calendario/dia/(?P<id>[^/]+)$", "calendario", "Vió agenda del {id}", "Vió agenda del {id}"),
    (r"^/reportes$", "reportes", "Vió reportes", "Vió reportes"),
    (r"^/reportes/productos-vendidos/export$", "reportes", "Exportó productos vendidos", "Exportó productos vendidos"),
    # Admin
    (r"^/administrador$", "admin", "Vió usuarios", "Vió usuarios"),
    (r"^/administrador/actividad$", "admin", "Vió historial de actividad", "Vió historial de actividad"),
    (r"^/administrador/notas$", "admin", "Vió mensajes de administración", "Respondió un mensaje"),
    (r"^/administrador/notas/chat\.json$", "admin", "Leyó chat de administración", "Leyó chat de administración"),
    (r"^/administrador/notas/resuelto$", "admin", "Marcó mensaje resuelto", "Marcó mensaje resuelto"),
    (r"^/administrador/usuarios/nuevo$", "admin", "Abrió alta de usuario", "Creó un usuario"),
    (r"^/administrador/usuarios/(?P<id>\d+)/editar$", "admin", "Abrió edición de usuario #{id}", "Editó usuario #{id}"),
    (r"^/administrador/usuarios/(?P<id>\d+)/password$", "admin", "Abrió contraseña de usuario #{id}", "Cambió contraseña de usuario #{id}"),
    (r"^/administrador/backup/descargar$", "admin", "Descargó backup", "Descargó backup"),
    (r"^/administrador/backup/restaurar$", "admin", "Abrió restauración de backup", "Restauró un backup"),
    (r"^/administrador/reset$", "admin", "Abrió reset de datos", "Reseteó datos del sistema"),
    # Portal vendedor
    (r"^/vendedor$", "portal", "Entró al portal vendedor", "Entró al portal vendedor"),
    (r"^/vendedor/presupuestos$", "portal", "Vió sus presupuestos", "Vió sus presupuestos"),
    (r"^/vendedor/presupuesto/(?P<id>\d+)$", "portal", "Vió presupuesto #{id}", "Vió presupuesto #{id}"),
    (r"^/vendedor/presupuesto/(?P<id>\d+)/eliminar$", "portal", "Abrió baja de presupuesto #{id}", "Eliminó presupuesto #{id}"),
    (r"^/vendedor/clientes$", "portal", "Vió sus clientes", "Vió sus clientes"),
    (r"^/vendedor/clientes/nuevo$", "portal", "Abrió alta de cliente", "Creó un cliente"),
    (r"^/vendedor/clientes/(?P<id>\d+)/editar$", "portal", "Abrió edición de cliente #{id}", "Editó cliente #{id}"),
    (r"^/vendedor/stock$", "portal", "Vió stock (portal)", "Vió stock (portal)"),
    (r"^/vendedor/listas$", "portal", "Vió listas (portal)", "Vió listas (portal)"),
    (r"^/vendedor/listas/(?P<id>[^/]+)/pdf$", "portal", "Descargó lista PDF", "Descargó lista PDF"),
    (r"^/vendedor/listas/(?P<id>[^/]+)/excel$", "portal", "Descargó lista Excel", "Descargó lista Excel"),
    (r"^/vendedor/listas/(?P<id>[^/]+)/png$", "portal", "Descargó lista imagen", "Descargó lista imagen"),
    (r"^/vendedor/ventas$", "portal", "Vió sus pedidos", "Vió sus pedidos"),
    (r"^/vendedor/ventas/(?P<id>\d+)$", "portal", "Vió pedido #{id}", "Vió pedido #{id}"),
    (r"^/vendedor/cuenta-corriente$", "portal", "Vió cuenta corriente", "Vió cuenta corriente"),
    (r"^/vendedor/reportes$", "portal", "Vió sus reportes", "Vió sus reportes"),
    (r"^/vendedor/catalogo-precios$", "portal", "Consultó catálogo (portal)", "Consultó catálogo (portal)"),
]

_COMPILED = [(re.compile(pat), grupo, gtxt, ptxt) for pat, grupo, gtxt, ptxt in _REGLAS]

_FALLBACK_SECCION = {
    "sesion": ("Navegó en sesión", "Hizo un cambio de sesión"),
    "pedidos": ("Vió pedidos", "Guardó un cambio en pedidos"),
    "despachos": ("Vió despachos", "Guardó un cambio en despachos"),
    "presupuestos": ("Vió presupuestos", "Guardó un cambio en presupuestos"),
    "productos": ("Vió productos", "Guardó un cambio en productos"),
    "stock": ("Vió stock", "Guardó un cambio en stock"),
    "caja": ("Vió caja", "Guardó un movimiento de caja"),
    "compras": ("Vió compras", "Guardó un cambio en compras"),
    "personas": ("Vió personas", "Guardó un cambio en personas"),
    "bancos": ("Vió bancos", "Guardó un cambio en bancos"),
    "calendario": ("Vió calendario", "Guardó un evento"),
    "reportes": ("Vió reportes", "Exportó un reporte"),
    "mensajes": ("Vió mensajes", "Envió o actualizó un mensaje"),
    "admin": ("Vió administración", "Guardó un cambio de administración"),
    "portal": ("Navegó el portal vendedor", "Guardó un cambio en el portal"),
    "inicio": ("Entró al inicio", "Entró al inicio"),
}


def describir_actividad(
    method: str,
    path: str,
    consulta: str = "",
    descripcion: str = "",
) -> AccionInfo:
    ruta = _norm_path(path)
    write = _is_write(method)
    grupo = ""
    texto_ruta = ""
    for rx, g, gtxt, ptxt in _COMPILED:
        m = rx.match(ruta)
        if not m:
            continue
        grupo = g
        plantilla = ptxt if write else gtxt
        texto_ruta = _fmt(plantilla, m.groupdict())
        if ruta == "/ventas" and not write:
            extra = _detalle_historial_ventas(consulta)
            if extra:
                texto_ruta = extra
        break
    if not grupo:
        grupo = grupo_de_ruta(ruta)

    desc = (descripcion or "").strip()
    if desc:
        return AccionInfo(desc, grupo or "", write or grupo == "sesion")
    if texto_ruta:
        return AccionInfo(texto_ruta, grupo, write or grupo == "sesion")
    gtxt, ptxt = _FALLBACK_SECCION.get(grupo, ("Navegó en el sistema", "Guardó un cambio"))
    return AccionInfo(ptxt if write else gtxt, grupo, write)


def _detalle_historial_ventas(consulta: str) -> str:
    qs = (consulta or "").lower()
    if "pestana=a_pagar" in qs:
        return "Vió pedidos a pagar"
    if "pestana=pagos" in qs:
        return "Vió pedidos pagos"
    if "pestana=ganancia" in qs:
        return "Vió ganancia por pedido"
    return ""
