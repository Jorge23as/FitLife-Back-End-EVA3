"""
Protección del login contra fuerza bruta (igual que en la EVA-2): 5
intentos fallidos desde una misma IP dentro de 10 minutos la bloquean por
10 minutos (responde 429).
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import BloqueoLogin

MAX_FALLOS = 5
VENTANA = timedelta(minutes=10)   # los 5 fallos tienen que ocurrir dentro de este tiempo
DURACION = timedelta(minutes=10)  # cuánto dura el bloqueo


def ip_del_cliente(request):
    # En el servidor Gunicorn solo escucha en el socket de Nginx, y Nginx
    # pisa X-Real-IP con la IP real (proxy_params), así que no se puede
    # falsificar. En local (runserver) no hay Nginx y uso REMOTE_ADDR.
    return request.headers.get('X-Real-IP') or request.META.get('REMOTE_ADDR') or '0.0.0.0'


def segundos_de_bloqueo(ip):
    """Segundos que le quedan de bloqueo a la IP (0 si no está bloqueada)."""
    fila = BloqueoLogin.objects.filter(ip=ip, bloqueado_hasta__gt=timezone.now()).first()
    if not fila:
        return 0
    return max(1, int((fila.bloqueado_hasta - timezone.now()).total_seconds()))


def registrar_fallo(ip):
    """
    Suma un fallo; al llegar a MAX_FALLOS bloquea la IP.
    Devuelve (intentos que le quedan, segundos de bloqueo o 0 si aún no se bloquea).
    """
    ahora = timezone.now()
    with transaction.atomic():
        # select_for_update: si dos workers registran a la vez, el segundo espera
        fila, _ = BloqueoLogin.objects.select_for_update().get_or_create(ip=ip, defaults={'primer_fallo': ahora})
        if fila.primer_fallo < ahora - VENTANA or (fila.bloqueado_hasta and fila.bloqueado_hasta <= ahora):
            # los fallos viejos o un bloqueo ya cumplido no cuentan: parte de cero
            fila.fallos, fila.primer_fallo, fila.bloqueado_hasta = 0, ahora, None
        fila.fallos += 1
        if fila.fallos >= MAX_FALLOS:
            fila.bloqueado_hasta = ahora + DURACION
        fila.save()
    if fila.bloqueado_hasta:
        return 0, int(DURACION.total_seconds())
    return MAX_FALLOS - fila.fallos, 0


def limpiar(ip):
    BloqueoLogin.objects.filter(ip=ip).delete()
