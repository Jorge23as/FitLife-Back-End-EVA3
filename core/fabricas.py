"""
Fábricas para las pruebas automáticas: arman los datos mínimos que necesita
cada prueba (un plan, un socio con su membresía pagada, una clase...).
"""
import itertools
from datetime import time, timedelta

from django.utils import timezone

from accesos.models import Sede
from clases.models import Actividad, Clase, Sala
from cuentas.models import Usuario
from cuentas.validadores import digito_verificador
from membresias import services
from membresias.models import Plan

CLAVE = 'Clave.Segura2026'
_numero = itertools.count(1)


def rut_nuevo():
    n = 20000000 + next(_numero)
    return f'{n}-{digito_verificador(n)}'


def crear_usuario(rol, username=None, **extra):
    n = next(_numero)
    usuario = Usuario(username=username or f'{rol.lower()}{n}', rol=rol, rut=rut_nuevo(), first_name='Nombre',
                      last_name=f'Apellido{n}', email=f'usuario{n}@prueba.cl', **extra)
    usuario.set_password(CLAVE)
    usuario.save()
    return usuario


def crear_plan(**datos):
    valores = {'nombre': f'Plan {next(_numero)}', 'precio': 30000, 'duracion_dias': 30, 'incluye_clases': True,
               'dias_congelamiento': 7}
    valores.update(datos)
    return Plan.objects.create(**valores)


def crear_socio(plan=None, username=None):
    """Socio con su membresía pagada hoy si se indica el plan."""
    socio = crear_usuario(Usuario.Rol.SOCIO, username).socio
    if plan:
        services.registrar_pago(socio, plan, 'EFECTIVO')
    return socio


def crear_sede(**datos):
    # 00:00 a 00:00 = abierta las 24 horas, así las pruebas no dependen de la hora en que se corren
    valores = {'nombre': f'Sede {next(_numero)}', 'direccion': 'Calle 123', 'aforo_maximo': 10,
               'hora_apertura': time(0, 0), 'hora_cierre': time(0, 0)}
    valores.update(datos)
    return Sede.objects.create(**valores)


def crear_clase(en=timedelta(days=1), cupo=2, sede=None, **datos):
    """Clase que parte en `en` (mañana por defecto) con sala, actividad e instructor propios."""
    n = next(_numero)
    sala = Sala.objects.create(sede=sede or Sede.objects.first() or crear_sede(), nombre=f'Sala {n}', capacidad=20)
    valores = {'actividad': Actividad.objects.create(nombre=f'Actividad {n}', duracion_minutos=60), 'sala': sala,
               'instructor': crear_usuario(Usuario.Rol.INSTRUCTOR).instructor, 'inicio': timezone.now() + en,
               'cupo': cupo}
    valores.update(datos)
    return Clase.objects.create(**valores)
