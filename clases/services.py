"""
Reglas de negocio de las clases grupales: reservas, cupos y lista de espera.

El problema del caso es el sobrecupo. Por eso toda operación que cambia
los cupos de una clase (reservar, cancelar, cambiar el cupo) parte
bloqueando la fila de la clase con select_for_update() dentro de una
transacción: si dos socios reservan el último cupo al mismo tiempo, el
segundo espera a que termine el primero y queda en lista de espera.

  reservar()               CONFIRMADA si hay cupo, si no ESPERA
  cancelar_reserva()       libera el cupo y sube al primero de la lista de espera
  promover_lista_espera()  llena los cupos libres por orden de llegada
  guardar_clase()          al subir el cupo también sube gente de la lista
  cancelar_clase()         cancela la clase y todas sus reservas
  marcar_asistencia()      el instructor pasa lista (ASISTIO / AUSENTE)
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.excepciones import Conflicto, ErrorDeNegocio
from membresias.services import membresia_para, motivo_sin_membresia, sincronizar_estados

from .models import Clase, Reserva

Estado = Reserva.Estado
# el instructor puede pasar lista desde 15 minutos antes de la clase
MARGEN_ASISTENCIA = timedelta(minutes=15)


def _bloquear(clase):
    """Vuelve a leer la clase bloqueando su fila hasta el fin de la transacción."""
    return Clase.objects.select_for_update().select_related('actividad', 'sala').get(pk=clase.pk)


def validar_reserva(socio, clase):
    """Revisa las reglas para reservar (sin guardar). Lanza ErrorDeNegocio con el motivo."""
    ahora = timezone.now()
    if clase.estado == Clase.Estado.CANCELADA:
        raise Conflicto('La clase fue cancelada.')
    if clase.inicio <= ahora:
        raise Conflicto('La clase ya comenzó; no se puede reservar.')

    sincronizar_estados(socio)
    membresia = membresia_para(socio, clase.fecha)
    if membresia is None:
        raise ErrorDeNegocio(f'No puede reservar: {motivo_sin_membresia(socio, clase.fecha)[1]}')
    plan = membresia.plan
    if not plan.incluye_clases:
        raise ErrorDeNegocio(f'Su plan "{plan}" no incluye clases grupales.')

    if clase.reservas.filter(socio=socio).exclude(estado=Estado.CANCELADA).exists():
        raise Conflicto('Ya tiene una reserva en esta clase.')
    # no puede estar en dos clases a la misma hora
    choque = (Reserva.objects.filter(socio=socio, estado__in=Reserva.ACTIVAS, clase__estado=Clase.Estado.PROGRAMADA,
                                     clase__inicio__lt=clase.fin, clase__fin__gt=clase.inicio)
              .select_related('clase__actividad').first())
    if choque:
        raise Conflicto(f'Ya tiene una reserva en {choque.clase} a la misma hora.')
    if plan.max_reservas_activas:
        activas = Reserva.objects.filter(socio=socio, estado__in=Reserva.ACTIVAS, clase__inicio__gt=ahora).count()
        if activas >= plan.max_reservas_activas:
            raise ErrorDeNegocio(f'Su plan "{plan}" permite {plan.max_reservas_activas} reservas activas a la vez. '
                                 'Cancele una o espere a que pase.')


@transaction.atomic
def reservar(socio, clase, reserva=None):
    """
    Reserva un cupo: CONFIRMADA si queda cupo, si no EN ESPERA. Las reglas
    se revisan otra vez con la clase bloqueada (pudo cambiar entre medio).
    """
    clase = _bloquear(clase)
    validar_reserva(socio, clase)
    reserva = reserva or Reserva()
    reserva.socio, reserva.clase = socio, clase
    reserva.estado = Estado.CONFIRMADA if clase.ocupados() < clase.cupo else Estado.ESPERA
    reserva.save()
    return reserva


def promover_lista_espera(clase):
    """
    Pasa a CONFIRMADA a los primeros de la lista de espera mientras haya
    cupo (por orden de llegada). Se llama con la clase ya bloqueada.
    """
    if clase.estado == Clase.Estado.CANCELADA or clase.inicio <= timezone.now():
        return []
    libres = clase.cupo - clase.ocupados()
    if libres <= 0:
        return []
    promovidas = list(clase.reservas.filter(estado=Estado.ESPERA).order_by('creada_en', 'id')[:libres])
    ahora = timezone.now()
    for reserva in promovidas:
        reserva.estado = Estado.CONFIRMADA
        reserva.promovida_en = ahora
        reserva.save(update_fields=['estado', 'promovida_en'])
    return promovidas


@transaction.atomic
def cancelar_reserva(reserva, motivo='Cancelada por el socio'):
    """Cancela la reserva; si tenía cupo, sube al primero de la lista de espera."""
    clase = _bloquear(reserva.clase)
    reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
    if reserva.estado not in Reserva.ACTIVAS:
        raise Conflicto('La reserva ya no está vigente.')
    if clase.inicio <= timezone.now():
        raise Conflicto('La clase ya comenzó; no se puede cancelar.')
    tenia_cupo = reserva.estado == Estado.CONFIRMADA
    reserva.estado = Estado.CANCELADA
    reserva.cancelada_en = timezone.now()
    reserva.motivo_cancelacion = motivo[:120]
    reserva.save(update_fields=['estado', 'cancelada_en', 'motivo_cancelacion'])
    promovidas = promover_lista_espera(clase) if tenia_cupo else []
    return reserva, promovidas


def cancelar_reservas_sin_cobertura(socio, motivo):
    """
    Cancela las reservas futuras del socio para días en que ya no tiene
    membresía (congelada o pago anulado), y así libera esos cupos.
    """
    canceladas = []
    pendientes = (Reserva.objects.filter(socio=socio, estado__in=Reserva.ACTIVAS, clase__inicio__gt=timezone.now())
                  .select_related('clase'))
    for reserva in pendientes:
        if membresia_para(socio, reserva.clase.fecha) is None:
            cancelar_reserva(reserva, motivo)
            canceladas.append(reserva)
    return canceladas


@transaction.atomic
def guardar_clase(clase):
    """
    Guarda una clase nueva o editada (ya validada con clean()). Si al editar
    subió el cupo, entra gente de la lista de espera.
    """
    if clase.pk:
        _bloquear(clase)
        # se vuelve a revisar con la fila bloqueada: alguien pudo reservar mientras se editaba
        if clase.cupo < clase.ocupados():
            raise Conflicto(f'Ya hay {clase.ocupados()} reservas confirmadas: el cupo no puede ser menor.')
    clase.save()
    return promover_lista_espera(clase)


@transaction.atomic
def cancelar_clase(clase, motivo='Clase cancelada por FitLife'):
    clase = _bloquear(clase)
    if clase.estado == Clase.Estado.CANCELADA:
        raise Conflicto('La clase ya estaba cancelada.')
    if clase.fin <= timezone.now():
        raise Conflicto('La clase ya terminó.')
    clase.estado = Clase.Estado.CANCELADA
    clase.save(update_fields=['estado'])
    return clase.reservas.filter(estado__in=Reserva.ACTIVAS).update(
        estado=Estado.CANCELADA, cancelada_en=timezone.now(), motivo_cancelacion=motivo[:120])


@transaction.atomic
def repetir_semana_siguiente(clase):
    """Copia la clase 7 días después (mismo horario, sala, instructor y cupo)."""
    copia = Clase(actividad=clase.actividad, instructor=clase.instructor, sala=clase.sala, cupo=clase.cupo,
                  inicio=clase.inicio + timedelta(days=7), fin=clase.fin + timedelta(days=7))
    copia.clean()
    copia.save()
    return copia


def marcar_asistencia(reserva, asistio):
    clase = reserva.clase
    if clase.estado == Clase.Estado.CANCELADA:
        raise Conflicto('La clase fue cancelada.')
    if timezone.now() < clase.inicio - MARGEN_ASISTENCIA:
        raise ErrorDeNegocio('Se puede pasar lista desde 15 minutos antes del inicio de la clase.')
    if reserva.estado not in Reserva.OCUPAN_CUPO:
        raise Conflicto('Solo se pasa lista a las reservas confirmadas.')
    reserva.estado = Estado.ASISTIO if asistio else Estado.AUSENTE
    reserva.save(update_fields=['estado'])
    return reserva
