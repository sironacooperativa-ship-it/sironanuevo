from django import forms

from core.date_fields import DATE_INPUT_FORMATS, date_input_widget

from .models import Evento


class EventoForm(forms.ModelForm):
    fecha = forms.DateField(
        input_formats=list(DATE_INPUT_FORMATS),
        widget=date_input_widget("form-control input-modern"),
    )
    hora = forms.TimeField(
        required=False,
        widget=forms.TimeInput(
            attrs={"class": "form-control input-modern", "type": "time"},
            format="%H:%M",
        ),
    )

    class Meta:
        model = Evento
        fields = ["fecha", "hora", "titulo", "tipo", "descripcion", "realizado"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control input-modern", "autocomplete": "off"}),
            "tipo": forms.Select(attrs={"class": "form-select input-modern"}),
            "descripcion": forms.Textarea(
                attrs={"class": "form-control input-modern calen-saas-textarea", "rows": 2}
            ),
            "realizado": forms.CheckboxInput(attrs={"class": "form-check-input", "role": "switch"}),
        }

