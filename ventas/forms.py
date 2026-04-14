from decimal import Decimal, InvalidOperation

from django import forms
from django.db.models import Q

from bancos.models import CuentaBancaria
from caja.models import MovimientoCaja
from core.date_fields import DATE_INPUT_FORMATS, date_input_widget
from personas.models import Comprador

from .models import Venta


class VentaCabeceraEditForm(forms.ModelForm):
    fecha_vencimiento_pago = forms.DateField(
        required=False,
        input_formats=list(DATE_INPUT_FORMATS),
        widget=date_input_widget(),
    )

    class Meta:
        model = Venta
        fields = ["comprador", "fecha_vencimiento_pago", "descuento_monto", "comision_porcentaje"]
        widgets = {
            "comprador": forms.Select(attrs={"class": "form-select"}),
            "descuento_monto": forms.TextInput(
                attrs={"class": "form-control", "inputmode": "decimal", "placeholder": "0"}
            ),
            "comision_porcentaje": forms.TextInput(
                attrs={"class": "form-control", "inputmode": "decimal", "placeholder": "4"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Comprador.objects.filter(habilitado=True).order_by("apellido", "nombre", "codigo")
        if self.instance and self.instance.comprador_id:
            qs = Comprador.objects.filter(Q(habilitado=True) | Q(pk=self.instance.comprador_id)).order_by(
                "apellido", "nombre", "codigo"
            )
        self.fields["comprador"].queryset = qs
        self.fields["comprador"].required = False

    def clean_descuento_monto(self):
        raw = (self.data.get("descuento_monto") or "").strip().replace(",", ".")
        try:
            d = Decimal(raw or "0")
        except InvalidOperation:
            raise forms.ValidationError("Monto no válido.")
        if d < 0:
            raise forms.ValidationError("El descuento no puede ser negativo.")
        sub = self.instance.subtotal_lineas
        if d > sub:
            raise forms.ValidationError("El descuento no puede superar el subtotal de líneas.")
        return d

    def clean_comision_porcentaje(self):
        raw = (self.data.get("comision_porcentaje") or "").strip().replace(",", ".")
        try:
            p = Decimal(raw or "0")
        except InvalidOperation:
            raise forms.ValidationError("Porcentaje no válido.")
        if p < 0:
            raise forms.ValidationError("La comisión no puede ser negativa.")
        return p


class VentaPagoForm(forms.ModelForm):
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
