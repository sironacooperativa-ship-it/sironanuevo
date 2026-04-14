from django import forms

from bancos.models import CuentaBancaria
from caja.models import MovimientoCaja


class VentaPagoForm(forms.ModelForm):
    fecha = forms.DateField(
        input_formats=["%d/%m/%y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "placeholder": "dd/mm/aa"}),
    )
    fecha_vencimiento_cheque = forms.DateField(
        required=False,
        input_formats=["%d/%m/%y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "placeholder": "dd/mm/aa"}),
    )

    class Meta:
        model = MovimientoCaja
        fields = [
            "fecha",
            "medio_pago",
            "cuenta_bancaria",
            "banco",
            "numero_cheque",
            "fecha_vencimiento_cheque",
        ]
        widgets = {
            "medio_pago": forms.Select(attrs={"class": "form-select", "id": "id_medio_pago"}),
            "cuenta_bancaria": forms.Select(attrs={"class": "form-select", "id": "id_cuenta_bancaria_pago"}),
            "banco": forms.TextInput(attrs={"class": "form-control"}),
            "numero_cheque": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuenta_bancaria"].queryset = CuentaBancaria.objects.filter(activa=True).order_by(
            "banco", "cuenta"
        )
        self.fields["cuenta_bancaria"].required = False
