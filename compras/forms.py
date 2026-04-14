from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from bancos.models import CuentaBancaria
from caja.models import MovimientoCaja
from personas.models import Proveedor
from productos.models import Producto


class CompraRegistrarForm(forms.Form):
    nombre_producto = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre del producto"}),
    )
    tipo_producto = forms.ChoiceField(
        choices=Producto.Tipo.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    proveedor = forms.ModelChoiceField(
        queryset=Proveedor.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    fecha_compra = forms.DateField(
        input_formats=["%d/%m/%y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "placeholder": "dd/mm/aa"}),
    )
    cantidad = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "1", "step": "1"}),
    )
    costo_unitario = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
    )

    fecha_vencimiento_pedido = forms.DateField(
        input_formats=["%d/%m/%y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "placeholder": "dd/mm/aa"}),
        label="Fecha de vencimiento del pedido / lote",
    )

    monto = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
        label="Monto total pagado (egreso en caja)",
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
    )
    medio_pago = forms.ChoiceField(
        choices=MovimientoCaja.MedioPago.choices,
        widget=forms.Select(attrs={"class": "form-select", "id": "id_medio_pago_compra"}),
    )
    banco = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    numero_cheque = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    fecha_vencimiento_cheque = forms.DateField(
        required=False,
        input_formats=["%d/%m/%y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "placeholder": "dd/mm/aa"}),
    )
    cuenta_bancaria = forms.ModelChoiceField(
        queryset=CuentaBancaria.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select", "id": "id_cuenta_bancaria_compra"}),
        label="Cuenta bancaria (transferencia / MP)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proveedor"].queryset = Proveedor.objects.filter(habilitado=True).order_by(
            "apellido", "nombre", "codigo"
        )
        self.fields["cuenta_bancaria"].queryset = CuentaBancaria.objects.filter(activa=True).order_by(
            "banco", "cuenta"
        )

    def clean(self):
        data = super().clean()
        if not data:
            return data
        medio = data.get("medio_pago")
        if medio in (MovimientoCaja.MedioPago.TRANSFERENCIA, MovimientoCaja.MedioPago.MERCADOPAGO):
            if not data.get("cuenta_bancaria"):
                raise ValidationError({"cuenta_bancaria": "Elegí la cuenta desde la que se paga."})
            if not (data.get("banco") or "").strip():
                raise ValidationError({"banco": "Indicá el banco o si es MercadoPago."})
        if medio == MovimientoCaja.MedioPago.CHEQUE:
            if not (data.get("numero_cheque") or "").strip():
                raise ValidationError({"numero_cheque": "Indicá el número de cheque."})
            if not data.get("fecha_vencimiento_cheque"):
                raise ValidationError({"fecha_vencimiento_cheque": "Indicá el vencimiento del cheque."})
        return data
