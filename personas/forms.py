from django import forms
from .models import Comprador, Proveedor, Vendedor


class _BasePersonaForm(forms.ModelForm):
    class Meta:
        fields = ["nombre", "apellido", "dni", "telefono", "mail", "direccion", "habilitado"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "apellido": forms.TextInput(attrs={"class": "form-control"}),
            "dni": forms.TextInput(attrs={"class": "form-control"}),
            "telefono": forms.TextInput(attrs={"class": "form-control"}),
            "mail": forms.EmailInput(attrs={"class": "form-control"}),
            "direccion": forms.TextInput(attrs={"class": "form-control"}),
            "habilitado": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class VendedorForm(_BasePersonaForm):
    class Meta(_BasePersonaForm.Meta):
        model = Vendedor
        fields = _BasePersonaForm.Meta.fields + ["comision_porcentaje"]
        widgets = {
            **_BasePersonaForm.Meta.widgets,
            "comision_porcentaje": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
        }


class ProveedorForm(_BasePersonaForm):
    class Meta(_BasePersonaForm.Meta):
        model = Proveedor


class CompradorForm(_BasePersonaForm):
    class Meta(_BasePersonaForm.Meta):
        model = Comprador

