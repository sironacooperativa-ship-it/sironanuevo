"""Repoblar cabecera y líneas de pedido/presupuesto desde POST tras un error de validación."""

from core.fecha_filtros import parse_fecha_param


def lineas_iniciales_desde_post(request) -> list[dict]:
    """Replica líneas `linea_producto` / `linea_cantidad` para json_script en plantillas."""
    pids = request.POST.getlist("linea_producto")
    qtys = request.POST.getlist("linea_cantidad")
    out: list[dict] = []
    for pid, qraw in zip(pids, qtys):
        ps = (pid or "").strip()
        qs = (qraw or "").strip()
        if not ps and not qs:
            continue
        qty = 1
        if qs:
            try:
                qty = int(qs)
            except ValueError:
                qty = 1
        if ps.isdigit():
            out.append({"producto_id": int(ps), "cantidad": max(1, qty)})
    return out


def repoblar_campos_cabecera_desde_post(request) -> dict:
    """Valores de cabecera tal como los envió el usuario (strings / ids opcionales)."""
    v = (request.POST.get("vendedor") or "").strip()
    c = (request.POST.get("comprador") or "").strip()
    raw_fecha = (request.POST.get("fecha_vencimiento_pago") or "").strip()
    fd = parse_fecha_param(raw_fecha)
    fecha_v = fd.strftime("%Y-%m-%d") if fd else raw_fecha
    return {
        "vendedor_id": int(v) if v.isdigit() else None,
        "comprador_id": int(c) if c.isdigit() else None,
        "fecha_vencimiento_pago": fecha_v,
        "descuento_monto": (request.POST.get("descuento_monto") or "").strip(),
        "comision_porcentaje": (request.POST.get("comision_porcentaje") or "").strip(),
        "aplica_comision": request.POST.get("aplica_comision") == "1",
    }
