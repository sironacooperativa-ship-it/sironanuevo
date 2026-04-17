from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from core.models import PerfilAcceso
from personas.models import Vendedor


User = get_user_model()


class UsuarioCrearForm(forms.ModelForm):
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)
    vendedor = forms.BooleanField(
        label="Vendedor",
        required=False,
        initial=True,
        help_text="Si está activo, el usuario ingresa al modo reducido (Portal Vendedor).",
    )

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
            solo_vendedor = bool(self.cleaned_data.get("vendedor"))
            PerfilAcceso.objects.update_or_create(
                usuario=user,
                defaults={"solo_vendedor": solo_vendedor},
            )
            # Si es vendedor, aseguramos un perfil Vendedor (para asociar pedidos/presupuestos).
            if solo_vendedor and not hasattr(user, "vendedor_perfil"):
                nombre = (user.first_name or "").strip() or user.username
                apellido = (user.last_name or "").strip() or "—"
                existente = Vendedor.objects.filter(
                    usuario__isnull=True,
                    nombre__iexact=nombre,
                    apellido__iexact=apellido,
                ).first()
                if existente:
                    existente.usuario = user
                    existente.save(update_fields=["usuario"])
                else:
                    Vendedor.objects.create(
                        nombre=nombre,
                        apellido=apellido,
                        usuario=user,
                        habilitado=True,
                    )
        return user


class UsuarioEditarForm(forms.ModelForm):
    vendedor = forms.BooleanField(
        label="Vendedor",
        required=False,
        help_text="Si está activo, el usuario queda limitado al modo reducido (Portal Vendedor).",
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active", "is_staff")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = getattr(self, "instance", None)
        solo = False
        if inst and getattr(inst, "pk", None):
            solo = bool(getattr(getattr(inst, "perfil_acceso", None), "solo_vendedor", False))
        self.fields["vendedor"].initial = solo

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.pk:
            solo_vendedor = bool(self.cleaned_data.get("vendedor"))
            PerfilAcceso.objects.update_or_create(
                usuario=user,
                defaults={"solo_vendedor": solo_vendedor},
            )
            if solo_vendedor and not hasattr(user, "vendedor_perfil"):
                nombre = (user.first_name or "").strip() or user.username
                apellido = (user.last_name or "").strip() or "—"
                existente = Vendedor.objects.filter(
                    usuario__isnull=True,
                    nombre__iexact=nombre,
                    apellido__iexact=apellido,
                ).first()
                if existente:
                    existente.usuario = user
                    existente.save(update_fields=["usuario"])
                else:
                    Vendedor.objects.create(
                        nombre=nombre,
                        apellido=apellido,
                        usuario=user,
                        habilitado=True,
                    )
        return user


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

