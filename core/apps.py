from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class FitLifeAdminConfig(AdminConfig):
    """El admin de Django, pero con mi sitio (core/admin_site.py) en vez del de por defecto."""
    default_site = 'core.admin_site.FitLifeAdminSite'


class CoreConfig(AppConfig):
    name = 'core'
    verbose_name = 'FitLife'
