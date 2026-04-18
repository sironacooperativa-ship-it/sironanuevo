"""Enlaces firmados para compartir presupuestos (p. ej. WhatsApp) sin login del cliente."""
from __future__ import annotations

import re
from urllib.parse import quote

from django.core import signing
from django.urls import reverse

from .models import Presupuesto

_SALT = "presupuesto.share.v1"
# Enlace válido ~4 meses (se puede regenerar desde la ficha)
_MAX_AGE = 60 * 60 * 24 * 120


def token_compartir_presupuesto(pk: int) -> str:
    return signing.dumps({"p": int(pk)}, salt=_SALT)


def pk_desde_token_compartir(token: str) -> int | None:
    try:
        data = signing.loads(token, salt=_SALT, max_age=_MAX_AGE)
        return int(data["p"])
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        return None


def url_presupuesto_compartido_absoluta(request, pk: int) -> str:
    tok = token_compartir_presupuesto(pk)
    rel = reverse("presupuesto_compartido", kwargs={"token": tok})
    return request.build_absolute_uri(rel)


def url_pdf_presupuesto_compartido_absoluta(request, pk: int) -> str:
    base = url_presupuesto_compartido_absoluta(request, pk).rstrip("/")
    return f"{base}?export=pdf"


def telefono_a_whatsapp_digits(telefono: str) -> str | None:
    """
    Solo dígitos para wa.me (el cliente debe cargar el número con código de país, ej. 54911…).
    """
    if not (telefono or "").strip():
        return None
    d = re.sub(r"\D+", "", telefono)
    if len(d) < 8:
        return None
    return d


def texto_whatsapp_presupuesto(request, presupuesto) -> str:
    link = url_presupuesto_compartido_absoluta(request, presupuesto.pk)
    if presupuesto.comprador_id and presupuesto.comprador:
        c = presupuesto.comprador
        hola = f"Hola {c.nombre}".strip() if c.nombre else "Hola"
    else:
        hola = "Hola"
    if presupuesto.estado == Presupuesto.Estado.APROBADO:
        tipo_doc = "orden de compra"
    else:
        tipo_doc = "presupuesto"
    return (
        f"{hola}, te envío el {tipo_doc} N.º {presupuesto.pk}.\n"
        f"Podés verlo y descargar PDF acá:\n{link}\n"
        f"Saludos."
    )


def whatsapp_compartir_url(request, presupuesto) -> str | None:
    """https://wa.me/...?text=... o None si no hay teléfono en el cliente."""
    if not presupuesto.comprador_id:
        return None
    tel = telefono_a_whatsapp_digits(presupuesto.comprador.telefono)
    if not tel:
        return None
    text = texto_whatsapp_presupuesto(request, presupuesto)
    return f"https://wa.me/{tel}?text={quote(text)}"


def contexto_compartir_presupuesto(request, presupuesto):
    """Contexto extra para la ficha de presupuesto (interna o portal vendedor)."""
    return {
        "url_compartir_cliente": url_presupuesto_compartido_absoluta(request, presupuesto.pk),
        "presupuesto_url_pdf": url_pdf_presupuesto_compartido_absoluta(request, presupuesto.pk),
        "whatsapp_compartir_url": whatsapp_compartir_url(request, presupuesto),
    }
