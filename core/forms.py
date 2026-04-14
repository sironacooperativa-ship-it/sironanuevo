from django.contrib.auth.forms import PasswordChangeForm


class SironaPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Contraseña actual"
        self.fields["new_password1"].label = "Nueva contraseña"
        self.fields["new_password2"].label = "Confirmar nueva contraseña"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
