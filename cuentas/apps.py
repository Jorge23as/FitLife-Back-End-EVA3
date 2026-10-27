from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CuentasConfig(AppConfig):
    name = 'cuentas'
    verbose_name = 'Cuentas y personas'

    def ready(self):
        from .roles import crear_grupos
        # después de cada migrate se crean/actualizan los grupos con sus permisos
        post_migrate.connect(crear_grupos, sender=self)
