from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_notaadmin_chat"),
    ]

    operations = [
        migrations.AddField(
            model_name="notaadmin",
            name="resuelto",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="En el mensaje raíz del hilo: administración marcó la consulta como resuelta.",
            ),
        ),
    ]
