"""Opciones del historial sin instanciar modelos ni ejecutar filtros de template por fila."""
from django.utils.html import format_html_join
from django.utils.text import Truncator


def opciones_productos(queryset, seleccionado):
    return format_html_join('', '<option value="{}"{}>{}</option>', (
        (pk, ' selected' if str(pk) == seleccionado else '', f'{codigo} — {Truncator(descripcion).chars(28)}')
        for pk, codigo, descripcion in queryset.values_list('pk', 'codigo', 'descripcion')
    ))


def opciones_personas(queryset, seleccionado):
    return format_html_join('', '<option value="{}"{}>{}</option>', (
        (pk, ' selected' if str(pk) == seleccionado else '', f'{codigo} — {apellido}, {nombre}')
        for pk, codigo, apellido, nombre in queryset.values_list('pk', 'codigo', 'apellido', 'nombre')
    ))
