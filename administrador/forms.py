from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction

from cuentas_compartidas.auth import PERMISO_CUENTAS_COMPARTIDAS
from core.models import PerfilAcceso
from personas.models import Vendedor
from productos.models import ListaPrecios


User = get_user_model()


def _permiso_cuentas_compartidas() -> Permission | None:
    app_label, codename = PERMISO_CUENTAS_COMPARTIDAS.split(".", 1)
    return Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()


def _guardar_permiso_cuentas_compartidas(user, habilitado: bool) -> None:
    permiso = _permiso_cuentas_compartidas()
    if not permiso:
        return
    if habilitado:
        user.user_permissions.add(permiso)
    else:
        user.user_permissions.remove(permiso)


def _vendedor_del_usuario(user) -> Vendedor | None:
    """Registro Vendedor vinculado a este usuario (OneToOne inversa)."""
    if not user or not getattr(user, "pk", None):
        return None
    return Vendedor.objects.filter(usuario_id=user.pk).first()


def _vincular_usuario_a_vendedor(user, v_destino: Vendedor) -> None:
    """
    Asigna user al registro de vendedor elegido y desvincula duplicados previos.
    Los clientes en Comprador.vendedor_asignado deben apuntar al mismo id que este registro.
    """
    for prev in Vendedor.objects.filter(usuario_id=user.pk).exclude(pk=v_destino.pk):
        prev.usuario = None
        prev.save(update_fields=["usuario"])
    v_destino.usuario = user
    v_destino.save(update_fields=["usuario"])


def _asegurar_vendedor_automatico(user) -> None:
    """Crea o enlaza un Vendedor por nombre/apellido (comportamiento anterior)."""
    if _vendedor_del_usuario(user) is not None:
        return
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


class UsuarioCrearForm(forms.ModelForm):
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput)
    vendedor = forms.BooleanField(
        label="Solo vendedor",
        required=False,
        initial=True,
        help_text=(
            "Si está activo, el usuario ingresa siempre al modo reducido. "
            "Si está desactivado y tiene vendedor vinculado, puede alternar entre modo completo y vendedor."
        ),
    )
    acceso_cuentas_compartidas = forms.BooleanField(
        label="Acceso a Gastos compartidos",
        required=False,
        help_text="Solo para usuarios staff. Habilita el menú interno de gastos, vencimientos y cancelaciones entre negocios.",
    )
    vinculo_vendedor = forms.ModelChoiceField(
        label="Vendedor existente en el sistema",
        queryset=Vendedor.objects.filter(habilitado=True).order_by("codigo"),
        required=False,
        empty_label="— Sin elegir: se crea o enlaza por nombre/apellido —",
        help_text=(
            "Si ya cargaste al vendedor en Personas y asignaste clientes, elegilo acá. "
            "Si no, el sistema puede crear otro registro distinto y los clientes no se verán en el portal."
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
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
        if cd.get("acceso_cuentas_compartidas") and not cd.get("is_staff"):
            self.add_error(
                "acceso_cuentas_compartidas",
                "Solo se puede habilitar Gastos compartidos a usuarios staff.",
            )
        vin = cd.get("vinculo_vendedor")
        if vin and vin.usuario_id:
            self.add_error(
                "vinculo_vendedor",
                f"Ese vendedor ya está vinculado al usuario «{vin.usuario.username}». "
                "Editá ese usuario o liberá el vínculo en Personas → Vendedores.",
            )
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
            vin = self.cleaned_data.get("vinculo_vendedor")
            with transaction.atomic():
                _guardar_permiso_cuentas_compartidas(
                    user,
                    bool(user.is_staff and self.cleaned_data.get("acceso_cuentas_compartidas")),
                )
                if vin:
                    _vincular_usuario_a_vendedor(user, vin)
                elif solo_vendedor:
                    _asegurar_vendedor_automatico(user)
        return user


class UsuarioEditarForm(forms.ModelForm):
    vendedor = forms.BooleanField(
        label="Solo vendedor",
        required=False,
        help_text=(
            "Si está activo, el usuario queda limitado al modo reducido. "
            "Si está desactivado y tiene vendedor vinculado, puede alternar entre modo completo y vendedor."
        ),
    )
    acceso_cuentas_compartidas = forms.BooleanField(
        label="Acceso a Gastos compartidos",
        required=False,
        help_text="Solo para usuarios staff. Habilita el menú interno de gastos, vencimientos y cancelaciones entre negocios.",
    )
    vinculo_vendedor = forms.ModelChoiceField(
        label="Vendedor existente en el sistema",
        queryset=Vendedor.objects.filter(habilitado=True).order_by("codigo"),
        required=False,
        empty_label="— Sin elegir: mantener actual o crear/enlazar por nombre —",
        help_text=(
            "Elegí el mismo registro que usás al asignar clientes (Compradores → vendedor asignado). "
            "Así el portal muestra «Mis clientes» correctamente."
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    listas_precios_bloqueadas = forms.ModelMultipleChoiceField(
        label="Listas de precio bloqueadas (portal vendedor)",
        queryset=ListaPrecios.objects.all().order_by("-es_farmacia", "nombre"),
        required=False,
        help_text="Estas listas NO estarán disponibles para este vendedor en el portal vendedor.",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "7"}),
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
            v = _vendedor_del_usuario(inst)
            self.fields["vinculo_vendedor"].initial = v.pk if v else None
            if v:
                self.fields["listas_precios_bloqueadas"].initial = list(
                    v.listas_precios_bloqueadas.values_list("pk", flat=True)
                )
            self.fields["acceso_cuentas_compartidas"].initial = bool(
                inst.is_staff and inst.has_perm(PERMISO_CUENTAS_COMPARTIDAS)
            )
        self.fields["vendedor"].initial = solo

    def clean(self):
        cd = super().clean()
        vin = cd.get("vinculo_vendedor")
        uid = getattr(self.instance, "pk", None)
        if vin and vin.usuario_id and uid and vin.usuario_id != uid:
            self.add_error(
                "vinculo_vendedor",
                f"Ese vendedor ya está vinculado al usuario «{vin.usuario.username}».",
            )
        if cd.get("acceso_cuentas_compartidas") and not cd.get("is_staff"):
            self.add_error(
                "acceso_cuentas_compartidas",
                "Solo se puede habilitar Gastos compartidos a usuarios staff.",
            )
        return cd

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and user.pk:
            solo_vendedor = bool(self.cleaned_data.get("vendedor"))
            PerfilAcceso.objects.update_or_create(
                usuario=user,
                defaults={"solo_vendedor": solo_vendedor},
            )
            vin = self.cleaned_data.get("vinculo_vendedor")
            with transaction.atomic():
                _guardar_permiso_cuentas_compartidas(
                    user,
                    bool(user.is_staff and self.cleaned_data.get("acceso_cuentas_compartidas")),
                )
                if vin:
                    _vincular_usuario_a_vendedor(user, vin)
                elif solo_vendedor and _vendedor_del_usuario(user) is None:
                    _asegurar_vendedor_automatico(user)

                # Listas de precios bloqueadas (solo si el usuario tiene vendedor vinculado).
                v = vin or _vendedor_del_usuario(user)
                if v:
                    v.listas_precios_bloqueadas.set(
                        self.cleaned_data.get("listas_precios_bloqueadas") or []
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
