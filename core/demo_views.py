from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone


def _require_demo_mode() -> None:
    if not getattr(settings, "DEMO_MODE", False):
        raise Http404()


def _demo_shell_ctx(*, active: str) -> dict:
    now = timezone.localtime()
    return {
        "demo_active": active,
        "demo_user": {"name": "Juan Pablo", "username": "juanpablo.demo"},
        "demo_now": now,
        "demo_title_suffix": " · Demo",
    }


@dataclass(frozen=True)
class DemoProducto:
    codigo: str
    descripcion: str
    tipo: str
    proveedor: str
    costo: str
    stock: int
    margen_pct: str
    precio: str
    estado: str


def demo_home(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="inicio")
    ctx.update(
        {
            "kpis": [
                {"title": "Ventas netas", "value": "$ 1.240.000,00", "sub": "Últimos 30 días", "icon": "badge-dollar-sign"},
                {"title": "Órdenes", "value": "128", "sub": "Últimos 30 días", "icon": "receipt"},
                {"title": "Compras", "value": "$ 410.000,00", "sub": "Últimos 30 días", "icon": "shopping-cart"},
                {"title": "Clientes activos", "value": "42", "sub": "Últimos 30 días", "icon": "users"},
            ],
            "pendientes": [
                {"id": "PED-10021", "cliente": "Cliente Demo", "total": "$ 18.900,00", "estado": "Pendiente"},
                {"id": "PED-10019", "cliente": "Cliente Demo 2", "total": "$ 7.450,00", "estado": "Pendiente"},
                {"id": "PED-10014", "cliente": "Cliente Demo 3", "total": "$ 31.200,00", "estado": "Pendiente"},
            ],
        }
    )
    return render(request, "demo/home.html", ctx)


def demo_productos(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="productos")
    ctx.update(
        {
            "kpi": {"productos": 2456, "activos": 2312, "stock_total": 152_487, "valor_total": "$ 152.487.650,00", "margen_prom": "28,6"},
            "productos": [
                DemoProducto("AC0001", "Producto Demo 1", "Accesorios", "DISMAR", "$ 3.700,00", 200, "31,0%", "$ 3.315,00", "Activo"),
                DemoProducto("ME0052", "Producto Demo 2", "Medicamentos", "SAVANT", "$ 955,50", 959, "28,0%", "$ 1.190,00", "Activo"),
                DemoProducto("OT0002", "Producto Demo 3", "Otros", "—", "$ 4.578,00", 0, "—", "$ 5.490,00", "Sin stock"),
            ],
        }
    )
    return render(request, "demo/productos.html", ctx)


def demo_producto_nuevo(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="productos")
    ctx.update(
        {
            "tipos": ["Medicamentos", "Accesorios", "Otros"],
            "proveedores": ["Proveedor Demo", "DISMAR", "SAVANT"],
        }
    )
    return render(request, "demo/producto_nuevo.html", ctx)


def demo_listas_precios(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="listas")
    ctx.update(
        {
            "lista": {
                "nombre": "Farmacias",
                "tipo": "Farmacia",
                "estado": "Activa",
                "actualizado": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
            },
            "kpi": {"productos": 2456, "activos": 2312, "valor_total": "$ 152.487.650,00", "margen_prom": "28,6%"},
            "rows": [
                DemoProducto("AC0001", "Producto Demo 1", "Accesorios", "DISMAR", "$ 3.700,00", 200, "31,0%", "$ 3.315,00", "Activo"),
                DemoProducto("AC0004", "Producto Demo 4", "Accesorios", "DISMAR", "$ 5.000,00", 100, "30,0%", "$ 6.500,00", "Activo"),
                DemoProducto("ME0013", "Producto Demo 5", "Medicamentos", "SAVANT", "$ 1.200,00", 0, "—", "$ 1.950,00", "Sin stock"),
            ],
        }
    )
    return render(request, "demo/listas_precios.html", ctx)


def demo_stock(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="stock")
    ctx.update(
        {
            "kpi": {"productos": 2456, "activos": 2312, "stock_total": 152_487, "valor_total": "$ 152.487.650,00", "sin_stock": 128},
            "rows": [
                {"codigo": "ME0052", "desc": "Producto Demo 2", "tipo": "Medicamentos", "stock": 959, "costo": "$ 955,50", "valor": "$ 915.214,50"},
                {"codigo": "OT0002", "desc": "Producto Demo 3", "tipo": "Otros", "stock": 0, "costo": "$ 4.578,00", "valor": "$ 0,00"},
            ],
            "movs": [
                {"fecha": "28/04 10:21", "tipo": "Entrada", "prod": "Producto Demo 2", "cant": 20},
                {"fecha": "27/04 18:04", "tipo": "Salida", "prod": "Producto Demo 1", "cant": 4},
            ],
        }
    )
    return render(request, "demo/stock.html", ctx)


def demo_ventas(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="ventas")
    ctx.update(
        {
            "kpi": {"ventas": "$ 1.240.000,00", "pedidos": 128, "pendientes": 12, "pagadas": 98},
            "rows": [
                {"id": "VTA-9001", "cliente": "Cliente Demo", "vendedor": "Vendedor Demo", "fecha": "28/04/2026 11:20", "total": "$ 18.900,00", "estado": "Pendiente"},
                {"id": "VTA-8993", "cliente": "Cliente Demo 2", "vendedor": "Vendedor Demo", "fecha": "27/04/2026 17:12", "total": "$ 7.450,00", "estado": "Pagada"},
            ],
        }
    )
    return render(request, "demo/ventas.html", ctx)


def demo_caja(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="caja")
    ctx.update(
        {
            "kpi": {"saldo": "$ 320.500,00", "ingresos": "$ 1.890.000,00", "egresos": "$ 1.569.500,00"},
            "rows": [
                {"fecha": "28/04/2026 11:35", "concepto": "Cobro venta VTA-9001", "medio": "Efectivo", "monto": "$ 18.900,00"},
                {"fecha": "28/04/2026 09:10", "concepto": "Pago proveedor Proveedor Demo", "medio": "Transferencia", "monto": "-$ 42.000,00"},
            ],
        }
    )
    return render(request, "demo/caja.html", ctx)


def demo_reportes(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="reportes")
    ctx.update(
        {
            "kpis": [
                {"title": "Ventas netas", "value": "$ 1.240.000,00", "sub": "Últimos 30 días", "icon": "badge-dollar-sign"},
                {"title": "Órdenes", "value": "128", "sub": "Últimos 30 días", "icon": "receipt"},
                {"title": "Compras", "value": "$ 410.000,00", "sub": "Últimos 30 días", "icon": "shopping-cart"},
                {"title": "Ticket promedio", "value": "$ 9.680,00", "sub": "Últimos 30 días", "icon": "sparkles"},
            ],
            "top": [
                {"name": "Cliente Demo", "value": "$ 84.200,00"},
                {"name": "Cliente Demo 2", "value": "$ 61.300,00"},
                {"name": "Cliente Demo 3", "value": "$ 54.990,00"},
            ],
        }
    )
    return render(request, "demo/reportes.html", ctx)


def demo_calendario(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="calendario")
    ctx.update(
        {
            "mes_label": "Abril 2026",
            "semana_labels": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"],
            # 6 semanas x 7 días (0 = celda vacía)
            "grid": [
                [0, 0, 0, 1, 2, 3, 4],
                [5, 6, 7, 8, 9, 10, 11],
                [12, 13, 14, 15, 16, 17, 18],
                [19, 20, 21, 22, 23, 24, 25],
                [26, 27, 28, 29, 30, 0, 0],
                [0, 0, 0, 0, 0, 0, 0],
            ],
            "eventos": {
                2: [{"t": "Visita Cliente Demo", "c": "primary"}],
                8: [{"t": "Cobro pendiente", "c": "warning"}],
                14: [{"t": "Compra Proveedor Demo", "c": "orange"}],
                22: [{"t": "Entrega pedido", "c": "success"}, {"t": "Recordatorio", "c": "muted"}],
                28: [{"t": "Reporte mensual", "c": "violet"}],
            },
        }
    )
    return render(request, "demo/calendario.html", ctx)


def demo_presupuestos(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="presupuestos")
    ctx.update(
        {
            "kpi": {"presupuestos": 36, "aprobados": 18, "pendientes": 12, "rechazados": 6},
            "rows": [
                {"id": "PRES-3001", "cliente": "Cliente Demo", "fecha": "28/04/2026 11:10", "total": "$ 10.000,00", "estado": "Pendiente"},
                {"id": "PRES-2993", "cliente": "Cliente Demo 2", "fecha": "27/04/2026 16:44", "total": "$ 24.500,00", "estado": "Aprobado"},
                {"id": "PRES-2987", "cliente": "Cliente Demo 3", "fecha": "26/04/2026 09:02", "total": "$ 7.990,00", "estado": "Rechazado"},
            ],
        }
    )
    return render(request, "demo/presupuestos.html", ctx)


def demo_pedidos(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="pedidos")
    ctx.update(
        {
            "kpi": {"pedidos": 128, "pendientes": 12, "pagadas": 98, "canceladas": 18},
            "rows": [
                {"id": "PED-10021", "fecha": "28/04/2026 11:20", "cliente": "Cliente Demo", "vendedor": "Vendedor Demo", "total": "$ 18.900,00", "estado": "Pendiente"},
                {"id": "PED-10019", "fecha": "28/04/2026 10:05", "cliente": "Cliente Demo 2", "vendedor": "Vendedor Demo", "total": "$ 7.450,00", "estado": "Pagada"},
                {"id": "PED-10014", "fecha": "27/04/2026 17:12", "cliente": "Cliente Demo 3", "vendedor": "Vendedor Demo 2", "total": "$ 31.200,00", "estado": "Cancelada"},
            ],
        }
    )
    return render(request, "demo/pedidos.html", ctx)


def demo_vendedor_home(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="vend_inicio")
    ctx["vendor_mode"] = True
    ctx.update(
        {
            "vendedor": {"codigo": "VEND-01", "nombre": "Vendedor", "apellido": "Demo"},
            "kpis": {"neto_30": "$ 420.000,00", "pedidos": 44, "pendientes": 6, "pagadas": 32},
            "pendientes": [
                {"id": "#1201", "fecha": "28/04/2026 11:20", "cliente": "Cliente Demo", "monto": "$ 18.900,00", "venc": "05/05/2026"},
                {"id": "#1198", "fecha": "27/04/2026 17:12", "cliente": "Cliente Demo 2", "monto": "$ 7.450,00", "venc": "03/05/2026"},
            ],
        }
    )
    return render(request, "demo/vendedor_home.html", ctx)


def demo_vendedor_reportes(request):
    _require_demo_mode()
    ctx = _demo_shell_ctx(active="vend_reportes")
    ctx["vendor_mode"] = True
    ctx.update(
        {
            "kpis": [
                {"title": "Ventas netas", "value": "$ 420.000,00", "sub": "Últimos 30 días", "icon": "badge-dollar-sign"},
                {"title": "Órdenes", "value": "44", "sub": "Últimos 30 días", "icon": "receipt"},
                {"title": "Pendientes", "value": "6", "sub": "Pagos", "icon": "clock"},
                {"title": "Ticket promedio", "value": "$ 9.545,00", "sub": "Últimos 30 días", "icon": "sparkles"},
            ],
        }
    )
    return render(request, "demo/vendedor_reportes.html", ctx)

