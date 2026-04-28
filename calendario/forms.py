from django import forms

from core.date_fields import DATE_INPUT_FORMATS, date_input_widget

from .models import Evento


class EventoForm(forms.ModelForm):
    fecha = forms.DateField(
        input_formats=list(DATE_INPUT_FORMATS),
        widget=date_input_widget("form-control calen-saas-input"),
    )

    class Meta:
        model = Evento
        fields = ["fecha", "titulo", "tipo", "descripcion"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control calen-saas-input", "autocomplete": "off"}),
            "tipo": forms.Select(attrs={"class": "form-select calen-saas-input"}),
            "descripcion": forms.Textarea(
                attrs={"class": "form-control calen-saas-input calen-saas-textarea", "rows": 3}
            ),
        }

