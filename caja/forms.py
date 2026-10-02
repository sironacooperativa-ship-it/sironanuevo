from decimal import Decimal, InvalidOperation

from django import forms

from bancos.models import CuentaBancaria
from core.date_fields import DATE_INPUT_FORMATS, date_input_widget
from core.money_decimal import parse_decimal_from_input, q2
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
        self.fields["tipo"].choices = [
            (v, lbl) for (v, lbl) in MovimientoCaja.Tipo.choices if v != MovimientoCaja.Tipo.ARQUEO
        ]

    def clean_monto(self):
        monto = self.cleaned_data.get("monto")
        if monto is None:
            return monto
        if isinstance(monto, Decimal) and monto <= 0:
            raise forms.ValidationError("El monto debe ser mayor a 0.")
        return monto


def _parse_saldo_arqueo(raw) -> Decimal:
    s = (raw or "").strip()
    if not s:
        return Decimal("0.00")
    try:
        d = parse_decimal_from_input(s)
    except InvalidOperation:
        raise forms.ValidationError("Monto no válido.")
    if d < 0:
        raise forms.ValidationError("El saldo no puede ser negativo.")
    return q2(d)


class ArqueoCajaForm(forms.Form):
    fecha = forms.DateField(
        input_formats=list(DATE_INPUT_FORMATS),
        widget=date_input_widget(),
        label="Arqueo al día",
    )
    saldo_efectivo = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal"}),
        label="Efectivo",
    )
    saldo_transferencia = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal"}),
        label="Transferencia / bancos",
    )
    saldo_mercadopago = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal"}),
        label="MercadoPago",
    )
    saldo_cheque = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal"}),
        label="Cheques",
    )
    saldo_otro = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal"}),
        label="Otro",
    )
    observaciones = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        label="Observaciones",
    )

    def clean_saldo_efectivo(self):
        return _parse_saldo_arqueo(self.cleaned_data.get("saldo_efectivo"))

    def clean_saldo_transferencia(self):
        return _parse_saldo_arqueo(self.cleaned_data.get("saldo_transferencia"))

    def clean_saldo_mercadopago(self):
        return _parse_saldo_arqueo(self.cleaned_data.get("saldo_mercadopago"))

    def clean_saldo_cheque(self):
        return _parse_saldo_arqueo(self.cleaned_data.get("saldo_cheque"))

    def clean_saldo_otro(self):
        return _parse_saldo_arqueo(self.cleaned_data.get("saldo_otro"))



class ActualizarSaldoForm(forms.Form):
    saldo_actual = forms.CharField(
        label="Saldo real disponible en caja",
        max_length=40,
        widget=forms.TextInput(attrs={"class": "form-control form-control-lg", "inputmode": "decimal", "placeholder": "Ej.: 150.000,00", "autocomplete": "off"}),
    )
    observaciones = forms.CharField(
        label="Observaciones (opcional)", required=False, max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    def clean_saldo_actual(self):
        from django.core.validators import DecimalValidator
        try:
            saldo = parse_decimal_from_input(self.cleaned_data['saldo_actual'])
            if not saldo.is_finite() or saldo < 0:
                raise forms.ValidationError("Ingresá un saldo de cero o mayor.")
            DecimalValidator(14, 2)(saldo)
            return q2(saldo)
        except (InvalidOperation, ValueError):
            raise forms.ValidationError("Ingresá un monto válido, por ejemplo 150.000,00.")
