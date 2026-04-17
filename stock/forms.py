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


