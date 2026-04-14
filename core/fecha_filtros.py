"""Parseo de fechas y rangos por período para listados filtrables."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

from django.utils import timezone


def parse_fecha_dashboard(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def rango_periodo(codigo: str) -> tuple[date | None, date | None]:
    """Rango inclusive (desde, hasta) según código de período; vacío si no reconocido."""
    today = timezone.localdate()
    if codigo == "7d":
        return today - timedelta(days=6), today
    if codigo == "30d":
        return today - timedelta(days=29), today
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
