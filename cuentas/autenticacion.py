"""
Autenticación de la API con la sesión de Django.

Es la SessionAuthentication de DRF (usa la cookie de sesión del login y
exige el token CSRF en POST, PUT, PATCH y DELETE). Solo le agrego
authenticate_header(): así una petición sin sesión responde 401 (no ha
iniciado sesión) en vez de 403 (no tiene permiso), y el JavaScript puede
mandar al login solo en el primer caso.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication


class SesionAuthentication(SessionAuthentication):
    def authenticate_header(self, request):
        return 'Session realm="fitlife"'


# Para Swagger: se documenta como autenticación por cookie de sesión
class SesionScheme(OpenApiAuthenticationExtension):
    target_class = SesionAuthentication
    name = 'cookieAuth'

    def get_security_definition(self, auto_schema):
        return {'type': 'apiKey', 'in': 'cookie', 'name': 'fitlife_sesion'}
