from django import forms

from .models import Evento


class EventoForm(forms.ModelForm):
    fecha = forms.DateField(
        input_formats=["%d/%m/%y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"class": "form-control", "placeholder": "dd/mm/aa"}),
    )

    class Meta:
        model = Evento
        fields = ["fecha", "titulo", "tipo", "descripcion"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "tipo": forms.Select(attrs={"class": "form-select"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

