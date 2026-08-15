"""Elimina tablas y migraciones del módulo Gastos compartidos (cuentas_compartidas)."""
from __future__ import annotations

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import connection


LEGACY_TABLES = (
    "cuentas_compartidas_cancelaciondeuda",
    "cuentas_compartidas_deudacompartida",
    "cuentas_compartidas_operacioncompartida",
    "cuentas_compartidas_negocio",
    "cuentas_compartidas_movimientoccmarcacion",
)


class Command(BaseCommand):
    help = (
        "Elimina tablas legacy de Gastos compartidos y limpia django_migrations. "
        "Idempotente: no falla si ya se ejecutó."
    )

    def handle(self, *args, **options):
        vendor = connection.vendor
        existing = set(connection.introspection.table_names())
        targets = [name for name in LEGACY_TABLES if name in existing]

        if targets:
            with connection.cursor() as cursor:
                if vendor == "sqlite":
                    cursor.execute("PRAGMA foreign_keys=OFF")
                for table in targets:
                    if vendor == "postgresql":
                        cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
                    else:
                        cursor.execute(f"DROP TABLE IF EXISTS {table}")
                if vendor == "sqlite":
                    cursor.execute("PRAGMA foreign_keys=ON")
            self.stdout.write(
                self.style.SUCCESS(
                    f"drop_cuentas_compartidas_legacy: eliminadas {len(targets)} tablas."
                )
            )
        else:
            self.stdout.write("drop_cuentas_compartidas_legacy: sin tablas legacy.")

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM django_migrations WHERE app = %s", ["cuentas_compartidas"])
            deleted_migrations = cursor.rowcount

        if deleted_migrations:
            self.stdout.write(
                f"drop_cuentas_compartidas_legacy: {deleted_migrations} filas en django_migrations."
            )

        permisos, _ = Permission.objects.filter(content_type__app_label="cuentas_compartidas").delete()
        tipos, _ = ContentType.objects.filter(app_label="cuentas_compartidas").delete()
        if permisos or tipos:
            self.stdout.write(
                f"drop_cuentas_compartidas_legacy: permisos={permisos}, content_types={tipos}."
            )
