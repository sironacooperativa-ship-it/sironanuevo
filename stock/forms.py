from django import forms

from productos.models import Producto
from .models import MovimientoStock


class MovimientoStockForm(forms.Form):
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.order_by("descripcion", "codigo"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    tipo = forms.ChoiceField(
        choices=MovimientoStock.Tipo.choices,
        widget=forms.Select(attrs={"class": "form-select", "id": "id_tipo"}),
    )
    cantidad = forms.IntegerField(
        min_value=1, widget=forms.NumberInput(attrs={"class": "form-control"})
    )

    numero_boleta = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    proveedor = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )

    numero_factura = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    destinatario = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": "form-control"})
    )

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get("tipo")
        if tipo == MovimientoStock.Tipo.ENTRADA:
            if not (cleaned.get("numero_boleta") or "").strip():
                self.add_error("numero_boleta", "Obligatorio al agregar stock.")
            if not (cleaned.get("proveedor") or "").strip():
                self.add_error("proveedor", "Obligatorio al agregar stock.")
        elif tipo == MovimientoStock.Tipo.SALIDA:
            if not (cleaned.get("numero_factura") or "").strip():
                self.add_error("numero_factura", "Obligatorio al quitar stock.")
            if not (cleaned.get("destinatario") or "").strip():
                self.add_error("destinatario", "Obligatorio al quitar stock.")
        return cleaned

