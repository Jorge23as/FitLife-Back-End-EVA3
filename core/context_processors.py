"""
Datos que llegan a todas las plantillas: el rol del usuario, para armar el
menú en el servidor (con la sesión de Django el servidor sabe quién es).
"""
from cuentas.models import Usuario
from cuentas.permisos import rol_de


def rol(request):
    rol_actual = rol_de(getattr(request, 'user', None))
    return {
        'rol': rol_actual,
        'es_staff_fitlife': rol_actual in Usuario.ROLES_STAFF,
        'es_admin_fitlife': rol_actual == Usuario.Rol.ADMIN,
    }
