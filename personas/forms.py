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
        fields = _BasePersonaForm.Meta.fields + ["vendedor_asignado"]
        widgets = {
            **_BasePersonaForm.Meta.widgets,
            "vendedor_asignado": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vendedor_asignado"].required = False
        self.fields["vendedor_asignado"].queryset = Vendedor.objects.filter(habilitado=True).order_by(
            "apellido", "nombre", "codigo"
        )

