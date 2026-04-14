from decimal import Decimal

from django import forms

from core.date_fields import DATE_INPUT_FORMATS, date_input_widget

from .models import Producto


class ProductoForm(forms.ModelForm):
    fecha_vencimiento = forms.DateField(
        required=False,
        input_formats=list(DATE_INPUT_FORMATS),
        widget=date_input_widget("form-control form-control-sm rounded-3"),
    )

    class Meta:
        model = Producto
        fields = [
            "descripcion",
            "tipo",
            "costo",
            "stock",
            "fecha_vencimiento",
            "porcentaje_ganancia",
            "precio_venta",
            "habilitado",
            "en_lista_precios",
        ]
        widgets = {
            "tipo": forms.Select(attrs={"class": "form-select form-select-sm rounded-3"}),
            "descripcion": forms.TextInput(attrs={"class": "form-control form-control-sm rounded-3"}),
            "costo": forms.NumberInput(
                attrs={"class": "form-control form-control-sm rounded-3", "step": "0.01"}
            ),
            "stock": forms.NumberInput(
                attrs={"class": "form-control form-control-sm rounded-3", "step": "1", "min": "0"}
            ),
            "porcentaje_ganancia": forms.NumberInput(
                attrs={"class": "form-control form-control-sm rounded-3", "step": "1", "min": "0"}
            ),
            "precio_venta": forms.NumberInput(
                attrs={"class": "form-control form-control-sm rounded-3", "step": "0.01"}
            ),
            "habilitado": forms.CheckboxInput(
                attrs={"class": "form-check-input", "role": "switch"}
            ),
            "en_lista_precios": forms.CheckboxInput(
                attrs={"class": "form-check-input", "role": "switch"}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        costo = cleaned.get("costo") or Decimal("0")
        pct = cleaned.get("porcentaje_ganancia") or Decimal("0")
        precio = cleaned.get("precio_venta")

        # Si el usuario deja el precio vacío, lo calculamos.
        if precio in (None, ""):
            cleaned["precio_venta_editado"] = False
            cleaned["precio_venta"] = (costo * (Decimal("1.0") + (pct / Decimal("100")))).quantize(
                Decimal("0.01")
            )
            return cleaned

        # Si el usuario ingresa un precio, lo respetamos.
        cleaned["precio_venta_editado"] = True
        return cleaned

