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

    def clean(self):
        cd = super().clean()
        # Evitar duplicados al crear
        if self.instance and self.instance.pk:
            return cd

        dni = (cd.get("dni") or "").strip()
        nombre = (cd.get("nombre") or "").strip()
        apellido = (cd.get("apellido") or "").strip()

        if dni:
            if Vendedor.objects.filter(dni__iexact=dni).exists():
                self.add_error("dni", "Ya existe un vendedor cargado con ese DNI.")
                raise forms.ValidationError("Ya existe un vendedor con ese DNI.")
        else:
            if nombre and apellido and Vendedor.objects.filter(
                nombre__iexact=nombre, apellido__iexact=apellido
            ).exists():
                raise forms.ValidationError(
                    "Ya existe un vendedor cargado con ese nombre y apellido. Si es la misma persona, editá el existente."
                )
        return cd


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
        self.fields["vendedor_asignado"].help_text = (
            "Debe ser el mismo registro vinculado al usuario del vendedor (Administración → Usuarios), "
            "para que vea estos clientes en el portal."
        )

    def clean(self):
        cd = super().clean()
        # Evitar duplicados al crear
        if self.instance and self.instance.pk:
            return cd

        dni = (cd.get("dni") or "").strip()
        nombre = (cd.get("nombre") or "").strip()
        apellido = (cd.get("apellido") or "").strip()

        if dni:
            if Comprador.objects.filter(dni__iexact=dni).exists():
                self.add_error("dni", "Ya existe un cliente cargado con ese DNI.")
                raise forms.ValidationError("Ya existe un cliente con ese DNI.")
        else:
            if nombre and apellido and Comprador.objects.filter(
                nombre__iexact=nombre, apellido__iexact=apellido
            ).exists():
                raise forms.ValidationError(
                    "Ya existe un cliente cargado con ese nombre y apellido. Si es la misma persona, editá el existente."
                )
        return cd

