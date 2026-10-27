"""
Errores de negocio y su respuesta en la API.

Los services (membresias, clases, accesos) lanzan ErrorDeNegocio cuando una
regla del caso impide la operación: "la clase ya comenzó", "membresía
vencida", "puede congelar entre 1 y 7 días"... El mismo error lo usa el
admin de Django (lo muestra como mensaje) y la API, donde este manejador lo
convierte en {"detail": "<motivo>"} con código 400 o 409.

También convierte el ProtectedError (borrar algo que tiene registros
asociados) en un 409 en vez de un error 500.
"""
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ErrorDeNegocio(Exception):
    def __init__(self, mensaje, codigo_http=status.HTTP_400_BAD_REQUEST):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo_http = codigo_http


class Conflicto(ErrorDeNegocio):
    """El estado actual no lo permite (ya reservada, ya anulado...): 409."""
    def __init__(self, mensaje):
        super().__init__(mensaje, status.HTTP_409_CONFLICT)


def manejador_excepciones(exc, context):
    if isinstance(exc, ErrorDeNegocio):
        return Response({'detail': exc.mensaje}, status=exc.codigo_http)
    if isinstance(exc, ProtectedError):
        return Response({'detail': 'No se puede eliminar: tiene registros asociados (integridad referencial). '
                                   'Puede desactivarlo en su lugar.'}, status=status.HTTP_409_CONFLICT)
    return exception_handler(exc, context)
