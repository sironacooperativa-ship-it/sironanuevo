from django.apps import AppConfig


class BancosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bancos"
    verbose_name = "Bancos"

    def ready(self) -> None:
        from . import signals  # noqa: F401
