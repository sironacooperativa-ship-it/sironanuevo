from decimal import Decimal, InvalidOperation

from django import forms
from django.db.models import Q

from bancos.models import CuentaBancaria
from caja.models import MovimientoCaja
from core.date_fields import DATE_INPUT_FORMATS, date_input_widget
from personas.models import Comprador

from .models import Venta


class VentaCabeceraEditForm(forms.ModelForm):
    """Solo cabecera del pedido pendiente: sin productos, cantidades, precios ni descuento."""

    fecha_vencimiento_pago = forms.DateField(
        required=False,
        input_formats=list(DATE_INPUT_FORMATS),
        widget=date_input_widget(),
    )

    class Meta:
        model = Venta
        fields = [
            "comprador",
            "fecha_vencimiento_pago",
            "comision_porcentaje",
            "aplica_comision",
        ]
        widgets = {
            "comprador": forms.Select(attrs={"class": "form-select"}),
            "comision_porcentaje": forms.TextInput(
                attrs={"class": "form-control", "inputmode": "decimal", "placeholder": "5"}
            ),
            "aplica_comision": forms.CheckboxInput(attrs={"class": "form-check-input"}),
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
        self.fields["aplica_comision"].label = "Aplicar comisión del vendedor (se liquida por mes en Comisiones)"

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
    detalle = forms.CharField(required=False, max_length=4000, widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Banco, referencia u otros datos"}))
    comprobante = forms.FileField(required=False, widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf,.png,.jpg,.jpeg,.webp"}))

    def clean_comprobante(self):
        archivo = self.cleaned_data.get("comprobante")
        if not archivo:
            return None
        if archivo.size > 10 * 1024 * 1024:
            raise forms.ValidationError("El comprobante debe pesar hasta 10 MB.")
        cabecera = archivo.read(16)
        archivo.seek(0)
        if cabecera.startswith(b"%PDF-"):
            archivo.tipo_validado = "application/pdf"
        elif cabecera.startswith(b"\x89PNG\r\n\x1a\n"):
            archivo.tipo_validado = "image/png"
        elif cabecera.startswith(b"\xff\xd8\xff"):
            archivo.tipo_validado = "image/jpeg"
        elif cabecera.startswith(b"RIFF") and cabecera[8:12] == b"WEBP":
            archivo.tipo_validado = "image/webp"
        else:
            raise forms.ValidationError("Adjuntá un PDF o una imagen PNG, JPG o WebP.")
        return archivo
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
        # El cobro de un pedido permite identificar la transferencia más tarde.
        self.instance._cobro_pedido = True
