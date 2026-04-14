from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model


User = get_user_model()


class UsuarioCrearForm(forms.ModelForm):
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active", "is_staff")

    def clean(self):
        cd = super().clean()
        p1 = cd.get("password1")
        p2 = cd.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cd

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UsuarioEditarForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active", "is_staff")


class UsuarioPasswordForm(forms.Form):
    password1 = forms.CharField(label="Nueva contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir nueva contraseña", widget=forms.PasswordInput)

    def clean(self):
        cd = super().clean()
        p1 = cd.get("password1")
        p2 = cd.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cd

