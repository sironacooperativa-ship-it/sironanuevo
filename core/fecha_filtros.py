"""Parseo de fechas y rangos por período para listados filtrables."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

from django.utils import timezone


def parse_fecha_param(s: str | None):
    """Parsea fechas desde query string o POST: ISO (yyyy-mm-dd) o dd/mm/aa."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_fecha_dashboard(s: str | None):
    """Alias usado en filtros de listados (compat.)."""
    return parse_fecha_param(s)


def fecha_filtro_value_iso(raw: str | None) -> str:
    """Valor para `input type=date`: ISO o cadena vacía."""
    d = parse_fecha_param(raw)
    return d.strftime("%Y-%m-%d") if d else ""


def rango_periodo(codigo: str) -> tuple[date | None, date | None]:
    """Rango inclusive (desde, hasta) según código de período; vacío si no reconocido."""
    today = timezone.localdate()
    if codigo == "7d":
        return today - timedelta(days=6), today
    if codigo == "30d":
        return today - timedelta(days=29), today
    if codigo == "60d":
        return today - timedelta(days=59), today
    if codigo == "180d":
        return today - timedelta(days=179), today
    if codigo == "365d":
        return today - timedelta(days=364), today
    if codigo == "mes":
        y, m = today.year, today.month
        start = date(y, m, 1)
        _, last = monthrange(y, m)
        return start, date(y, m, last)
    if codigo == "mes_ant":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        y, m = last_prev.year, last_prev.month
        start = date(y, m, 1)
        _, last = monthrange(y, m)
        return start, date(y, m, last)
    return None, None


def trunc_to_date(val) -> date | None:
    """
    Normaliza la salida de TruncDate / TruncMonth / TruncWeek (SQLite suele devolver
    `date` en TruncDate; Postgres puede devolver `datetime`). No usar is_aware() sobre `date`.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        if timezone.is_aware(val):
            return timezone.localtime(val).date()
        return val.date()
    if isinstance(val, date):
        return val
    return None


def trunc_to_month_start(val) -> date | None:
    """Primer día del mes a partir de un valor truncado por mes."""
    d = trunc_to_date(val)
    return d.replace(day=1) if d else None


def trunc_chart_label(val, fmt: str) -> str:
    """Etiqueta para gráficos a partir de un bucket truncado."""
    d = trunc_to_date(val)
    if d is not None:
        return d.strftime(fmt)
    if isinstance(val, datetime):
        return val.strftime(fmt)
    return ""
