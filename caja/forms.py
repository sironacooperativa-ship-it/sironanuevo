from decimal import Decimal

from django import forms

from bancos.models import CuentaBancaria
from core.date_fields import DATE_INPUT_FORMATS, date_input_widget
from personas.models import Vendedor

from .models import MovimientoCaja


class MovimientoCajaForm(forms.ModelForm):
    fecha = forms.DateField(
        input_formats=list(DATE_INPUT_FORMATS),
        widget=date_input_widget(),
    )
    fecha_vencimiento_cheque = forms.DateField(
        required=False,
        input_formats=list(DATE_INPUT_FORMATS),
        widget=date_input_widget(),
    )

    class Meta:
        model = MovimientoCaja
        fields = [
            "fecha",
            "operacion",
            "tipo",
            "monto",
            "medio_pago",
            "cuenta_bancaria",
            "banco",
            "numero_cheque",
            "fecha_vencimiento_cheque",
            "vendedor",
        ]
        widgets = {
            "operacion": forms.TextInput(attrs={"class": "form-control"}),
            "tipo": forms.Select(attrs={"class": "form-select"}),
            "monto": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "medio_pago": forms.Select(attrs={"class": "form-select", "id": "id_medio_pago"}),
            "cuenta_bancaria": forms.Select(attrs={"class": "form-select", "id": "id_cuenta_bancaria"}),
            "banco": forms.TextInput(attrs={"class": "form-control"}),
            "numero_cheque": forms.TextInput(attrs={"class": "form-control"}),
            "vendedor": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vendedor"].queryset = Vendedor.objects.filter(habilitado=True).order_by(
            "apellido", "nombre", "codigo"
        )
        self.fields["vendedor"].required = False
        # En selects opcionales, evitar el placeholder "---------" (queremos vacío).
        try:
            self.fields["vendedor"].empty_label = ""
        except Exception:
            pass
        self.fields["cuenta_bancaria"].queryset = CuentaBancaria.objects.filter(activa=True).order_by(
            "banco", "cuenta"
        )
        self.fields["cuenta_bancaria"].required = False
        try:
            self.fields["cuenta_bancaria"].empty_label = ""
        except Exception:
            pass
        # ChoiceField con blank: poner etiqueta vacía (en vez de "---------").
        try:
            self.fields["tipo"].choices = [(v, ("" if v == "" else lbl)) for (v, lbl) in self.fields["tipo"].choices]
        except Exception:
            pass

    def clean_monto(self):
        monto = self.cleaned_data.get("monto")
        if monto is None:
            return monto
        if isinstance(monto, Decimal) and monto <= 0:
            raise forms.ValidationError("El monto debe ser mayor a 0.")
        return monto

