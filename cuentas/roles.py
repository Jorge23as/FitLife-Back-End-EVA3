"""
Roles y grupos de Django.

Cada rol tiene un grupo de Django. El grupo lleva los permisos por modelo
(add / change / delete / view) que respeta el admin de Django:
  - Administradores: todo sobre los modelos de FitLife.
  - Recepción: ve todo, registra pagos, congela membresías, maneja
    reservas y visitas; no puede borrar nada ni tocar usuarios ni planes.
  - Instructores y Socios: sin permisos en el admin (no son staff).

Los grupos se crean o se actualizan solos después de cada migrate (señal
post_migrate, ver apps.py). En la API los permisos van por rol (permisos.py).
"""
from django.apps import apps as apps_globales
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Group, Permission

APPS_FITLIFE = ['cuentas', 'membresias', 'clases', 'accesos']

GRUPOS = {
    'ADMIN': 'Administradores',
    'RECEPCION': 'Recepción',
    'INSTRUCTOR': 'Instructores',
    'SOCIO': 'Socios',
}

# además de "ver" todos los modelos
PERMISOS_RECEPCION = [
    ('cuentas', 'change_socio'),
    ('membresias', 'add_pago'),
    ('membresias', 'change_pago'),
    ('membresias', 'change_membresia'),
    ('clases', 'add_reserva'),
    ('clases', 'change_reserva'),
    ('accesos', 'change_visita'),
]


def crear_grupos(using='default', **kwargs):
    # los permisos de cada modelo los crea Django después de migrar cada app;
    # los aseguro acá para no depender del orden en que llega la señal
    for etiqueta in APPS_FITLIFE:
        create_permissions(apps_globales.get_app_config(etiqueta), verbosity=0, using=using)

    de_fitlife = Permission.objects.using(using).filter(content_type__app_label__in=APPS_FITLIFE)
    grupos = {rol: Group.objects.using(using).get_or_create(name=nombre)[0] for rol, nombre in GRUPOS.items()}

    grupos['ADMIN'].permissions.set(de_fitlife)
    extra = [de_fitlife.get(content_type__app_label=app, codename=codigo) for app, codigo in PERMISOS_RECEPCION]
    grupos['RECEPCION'].permissions.set(list(de_fitlife.filter(codename__startswith='view_')) + extra)
    grupos['INSTRUCTOR'].permissions.clear()
    grupos['SOCIO'].permissions.clear()


def sincronizar_grupo(usuario):
    """Deja al usuario solo en el grupo de su rol."""
    grupo, _ = Group.objects.get_or_create(name=GRUPOS[usuario.rol])
    usuario.groups.set([grupo])
