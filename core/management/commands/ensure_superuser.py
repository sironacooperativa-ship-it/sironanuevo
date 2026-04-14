from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea un superusuario si no existe (usa variables de entorno)."

    def handle(self, *args, **options):
        username = (os.environ.get("DJANGO_SUPERUSER_USERNAME") or "").strip()
        email = (os.environ.get("DJANGO_SUPERUSER_EMAIL") or "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD") or ""

        if not username or not password:
            self.stdout.write("ensure_superuser: faltan DJANGO_SUPERUSER_USERNAME/PASSWORD; no se crea usuario.")
            return

        User = get_user_model()
        u = User.objects.filter(username=username).first()
        if u:
            self.stdout.write(f"ensure_superuser: ya existe '{username}', no se modifica.")
            return

        u = User.objects.create_superuser(username=username, email=email or None, password=password)
        self.stdout.write(f"ensure_superuser: superusuario creado '{u.username}'.")

