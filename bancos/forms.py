from decimal import Decimal

from django import forms

from caja.models import MovimientoCaja

from .models import CuentaBancaria, Gasto


class CuentaBancariaForm(forms.ModelForm):
    class Meta:
        model = CuentaBancaria
        fields = ["banco", "cuenta", "saldo_inicial", "activa"]
        widgets = {
            "banco": forms.TextInput(attrs={"class": "form-control"}),
            "cuenta": forms.TextInput(attrs={"class": "form-control"}),
            "saldo_inicial": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class AjusteCuentaForm(forms.Form):
    fecha = forms.DateField(
        input_formats=["%d/%m/%y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "placeholder": "dd/mm/aa"}),
    )
    monto = forms.DecimalField(
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
    )
    tipo = forms.ChoiceField(
        choices=[
            ("DEB", "Egreso de la cuenta (impuesto, comisión, débito)"),
            ("CRE", "Ingreso / acreditación en la cuenta"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    concepto = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej.: IIBB, comisión bancaria"}),
    )


class GastoTransferenciaForm(forms.Form):
    fecha = forms.DateField(
        input_formats=["%d/%m/%y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "placeholder": "dd/mm/aa"}),
    )
    descripcion = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "form-control"}))
    monto = forms.DecimalField(
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
    )
    cuenta_bancaria = forms.ModelChoiceField(
        queryset=CuentaBancaria.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    banco_detalle = forms.CharField(
        max_length=100,
        required=False,
        label="Referencia / detalle banco (opcional)",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuenta_bancaria"].queryset = CuentaBancaria.objects.filter(activa=True).order_by(
            "banco", "cuenta"
        )
