"""Widgets de fecha con selector nativo (HTML5) y formato ISO (yyyy-mm-dd)."""

from django import forms

ISO_DATE = "%Y-%m-%d"
# ISO para el navegador; dd/mm por compatibilidad con datos viejos o pegados
DATE_INPUT_FORMATS: tuple[str, ...] = (ISO_DATE, "%d/%m/%y", "%d/%m/%Y")


def date_input_widget(css_class: str = "form-control") -> forms.DateInput:
    return forms.DateInput(
        format=ISO_DATE,
        attrs={"type": "date", "class": css_class},
    )


def date_input_widget_sm() -> forms.DateInput:
    return date_input_widget("form-control form-control-sm")
