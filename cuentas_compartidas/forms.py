from datetime import date
from decimal import Decimal

from django import forms

from core.date_fields import DATE_INPUT_FORMATS, date_input_widget
from core.money_decimal import q2

from .models import CancelacionDeuda, Negocio, OperacionCompartida


class NegocioForm(forms.ModelForm):
    class Meta:
        model = Negocio
        fields = ["nombre", "activo"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej.: Local Centro"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class OperacionCompartidaForm(forms.ModelForm):
    class Meta:
        model = OperacionCompartida
        fields = ["fecha", "concepto", "tipo", "pagador", "monto_total", "observaciones"]
        labels = {
            "pagador": "Local que pagó",
            "monto_total": "Monto pagado",
        }
        widgets = {
            "fecha": date_input_widget(),
            "concepto": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej.: Compra mayorista"}),
            "tipo": forms.Select(attrs={"class": "form-select"}),
            "pagador": forms.Select(attrs={"class": "form-select", "id": "id_pagador"}),
            "monto_total": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0.01", "id": "id_monto_total"}
            ),
            "observaciones": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self.negocios = list(kwargs.pop("negocios", Negocio.objects.filter(activo=True)))
        super().__init__(*args, **kwargs)
        pagador_qs = Negocio.objects.filter(activo=True)
        if self.instance and self.instance.pk and self.instance.pagador_id:
            pagador_qs = Negocio.objects.filter(pk=self.instance.pagador_id) | pagador_qs
        self.fields["pagador"].queryset = pagador_qs.distinct().order_by("nombre")
        deudas_actuales = {}
        if self.instance and self.instance.pk:
            deudas_actuales = {
                deuda.deudor_id: deuda
                for deuda in self.instance.deudas.all()
            }
        for negocio in self.negocios:
            deuda_actual = deudas_actuales.get(negocio.pk)
            self.fields[f"incluir_{negocio.pk}"] = forms.BooleanField(
                required=False,
                label=negocio.nombre,
                initial=bool(deuda_actual),
                widget=forms.CheckboxInput(
                    attrs={
                        "class": "form-check-input deuda-toggle",
                        "data-negocio-id": str(negocio.pk),
                    }
                ),
            )
            self.fields[f"monto_{negocio.pk}"] = forms.DecimalField(
                required=False,
                min_value=Decimal("0.01"),
                initial=deuda_actual.monto if deuda_actual else None,
                widget=forms.NumberInput(
                    attrs={
                        "class": "form-control deuda-monto",
                        "step": "0.01",
                        "min": "0.01",
                        "data-negocio-id": str(negocio.pk),
                    }
                ),
            )
            self.fields[f"vencimiento_{negocio.pk}"] = forms.DateField(
                required=False,
                input_formats=list(DATE_INPUT_FORMATS),
                initial=deuda_actual.vencimiento if deuda_actual else None,
                widget=date_input_widget(),
            )

    def clean(self):
        cleaned = super().clean()
        pagador = cleaned.get("pagador")
        monto_total = cleaned.get("monto_total")
        deudas = []
        for negocio in self.negocios:
            incluido = cleaned.get(f"incluir_{negocio.pk}")
            monto = cleaned.get(f"monto_{negocio.pk}")
            vencimiento = cleaned.get(f"vencimiento_{negocio.pk}")
            if pagador and negocio.pk == pagador.pk and incluido:
                self.add_error(f"incluir_{negocio.pk}", "El local que pagó no puede figurar como deudor.")
                continue
            if incluido and not monto:
                self.add_error(f"monto_{negocio.pk}", "Indicá el monto que debe reintegrar.")
            if not incluido and (monto or vencimiento):
                self.add_error(f"incluir_{negocio.pk}", "Marcá el local para cargar su parte.")
            if incluido and monto and (not pagador or negocio.pk != pagador.pk):
                deudas.append({"negocio": negocio, "monto": monto, "vencimiento": vencimiento})
        if not deudas:
            raise forms.ValidationError("Seleccioná al menos un local que deba reintegrar el pago.")
        if monto_total is not None:
            suma = sum(Decimal(item["monto"]) for item in deudas)
            if q2(suma) != q2(monto_total):
                raise forms.ValidationError(
                    f"La suma de los montos parciales ({q2(suma)}) debe coincidir con el monto pagado ({q2(monto_total)})."
                )
        cleaned["deudas"] = deudas
        return cleaned


class CancelacionDeudaForm(forms.ModelForm):
    class Meta:
        model = CancelacionDeuda
        fields = ["fecha", "monto", "medio", "detalle"]
        widgets = {
            "fecha": date_input_widget(),
            "monto": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "medio": forms.Select(attrs={"class": "form-select"}),
            "detalle": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej.: transferencia, cajones, compra compensada"}),
        }

    def __init__(self, *args, deuda=None, **kwargs):
        self.deuda = deuda
        super().__init__(*args, **kwargs)
        self.fields["fecha"].initial = self.fields["fecha"].initial or date.today()

    def clean_monto(self):
        monto = self.cleaned_data["monto"]
        if self.deuda and monto > self.deuda.pendiente:
            raise forms.ValidationError("El monto no puede superar el saldo pendiente.")
        return monto
