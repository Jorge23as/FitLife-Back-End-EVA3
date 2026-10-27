"""
python manage.py actualizar_membresias

Vence las membresías que pasaron su término y reactiva las congeladas cuyo
congelamiento terminó. En el servidor lo corre cron todos los días a las
00:05 (ver deploy/). La app igual lo hace antes de validar un acceso,
reservar o listar, así que el cron solo deja la base al día de noche.
"""
from django.core.management.base import BaseCommand

from membresias.services import sincronizar_estados


class Command(BaseCommand):
    help = 'Actualiza los estados de las membresías según la fecha (vencidas y fin de congelamiento).'

    def handle(self, *args, **opciones):
        reactivadas, vencidas = sincronizar_estados()
        self.stdout.write(self.style.SUCCESS(f'{vencidas} membresía(s) vencida(s), {reactivadas} reactivada(s).'))
