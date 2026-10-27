"""
Permisos de la API por rol.

DRF llama a has_permission() antes de entrar a la vista. Si devuelve
False responde 401 (no hay sesión) o 403 (hay sesión, pero el rol no
puede hacer eso). Se pueden combinar: [EsSocio | EsStaff].
El superusuario cuenta como administrador.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Usuario


def rol_de(usuario):
    if not usuario or not usuario.is_authenticated:
        return None
    if usuario.is_superuser:
        return Usuario.Rol.ADMIN
    return usuario.rol


class EsAdmin(BasePermission):
    message = 'Acción reservada para el administrador de FitLife.'

    def has_permission(self, request, view):
        return rol_de(request.user) == Usuario.Rol.ADMIN


class EsStaff(BasePermission):
    """Personal del gimnasio: recepción o administración."""
    message = 'Acción reservada para el personal de FitLife (recepción o administración).'

    def has_permission(self, request, view):
        return rol_de(request.user) in Usuario.ROLES_STAFF


class EsSocio(BasePermission):
    message = 'Acción reservada para socios de FitLife.'

    def has_permission(self, request, view):
        return rol_de(request.user) == Usuario.Rol.SOCIO


class EsInstructor(BasePermission):
    message = 'Acción reservada para instructores.'

    def has_permission(self, request, view):
        return rol_de(request.user) == Usuario.Rol.INSTRUCTOR


class LecturaPublicaEscrituraAdmin(BasePermission):
    """Ver: cualquiera, incluso sin sesión (planes, horario). Crear, editar y borrar: administrador."""
    message = 'Solo el administrador puede modificar estos datos.'

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or rol_de(request.user) == Usuario.Rol.ADMIN


class LecturaStaffEscrituraAdmin(BasePermission):
    """Ver: recepción y administración. Crear, editar y borrar: administrador."""
    message = 'Solo el administrador puede modificar estos datos.'

    def has_permission(self, request, view):
        rol = rol_de(request.user)
        if request.method in SAFE_METHODS:
            return rol in Usuario.ROLES_STAFF
        return rol == Usuario.Rol.ADMIN
