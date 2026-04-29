# Generated manually for chat-style notas admin

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def forwards_leida_usuario(apps, schema_editor):
    NotaAdmin = apps.get_model("core", "NotaAdmin")
    # Mensajes de usuario hacia admin: no requieren "leído por usuario"
    NotaAdmin.objects.filter(es_staff=False).update(leida_usuario=True)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0002_notaadmin"),
    ]

    operations = [
        migrations.AddField(
            model_name="notaadmin",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="respuestas",
                to="core.notaadmin",
            ),
        ),
        migrations.AddField(
            model_name="notaadmin",
            name="es_staff",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="notaadmin",
            name="leida_usuario",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="notaadmin",
            name="creado_por",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="notas_admin_enviadas_staff",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(forwards_leida_usuario, migrations.RunPython.noop),
    ]
