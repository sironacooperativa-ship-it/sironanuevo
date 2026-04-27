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
        fields = _BasePersonaForm.Meta.fields + [
            "comision_porcentaje",
            "es_jefe_grupo",
            "comision_grupo_porcentaje",
            "vendedores_a_cargo",
        ]
        widgets = {
            **_BasePersonaForm.Meta.widgets,
            "comision_porcentaje": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "es_jefe_grupo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "comision_grupo_porcentaje": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "vendedores_a_cargo": forms.SelectMultiple(attrs={"class": "form-select", "size": "8"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Vendedor.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["vendedores_a_cargo"].queryset = qs
        self.fields["vendedores_a_cargo"].required = False
        self.fields["vendedores_a_cargo"].help_text = (
            "Elegí los vendedores cuyas ventas generan comisión adicional para este vendedor."
        )

    def clean(self):
        cd = super().clean()
        es_jefe = bool(cd.get("es_jefe_grupo"))
        pct_grupo = cd.get("comision_grupo_porcentaje")
        vendedores_a_cargo = cd.get("vendedores_a_cargo")
        if not es_jefe:
            cd["comision_grupo_porcentaje"] = pct_grupo or 0
        elif pct_grupo is None or pct_grupo <= 0:
            self.add_error(
                "comision_grupo_porcentaje",
                "Indicá un porcentaje mayor a 0 para el vendedor a cargo de grupo.",
            )
        if es_jefe and vendedores_a_cargo is not None and not vendedores_a_cargo.exists():
            self.add_error(
                "vendedores_a_cargo",
                "Elegí al menos un vendedor a cargo para activar esta categoría.",
            )

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

    def save(self, commit=True):
        vendedor = super().save(commit=commit)
        if commit and not self.cleaned_data.get("es_jefe_grupo"):
            vendedor.vendedores_a_cargo.clear()
        return vendedor


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

