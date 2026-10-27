"""
Reglas de negocio de planes, pagos y membresías.

Estados de una membresía y quién los cambia:
  pago registrado              -> ACTIVA     registrar_pago()
  recepción la congela         -> CONGELADA  congelar()
  termina el congelamiento     -> ACTIVA     sincronizar_estados() o descongelar()
  pasa la fecha de término     -> VENCIDA    sincronizar_estados()
  se anula el pago             -> CANCELADA  anular_pago()

Las vistas de la API y el admin de Django llaman a estas funciones, así
las reglas están en un solo lugar. Si una regla no se cumple lanzan
ErrorDeNegocio con el motivo, que se le muestra al usuario.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, Max, OuterRef
from django.utils import timezone

from core.excepciones import Conflicto, ErrorDeNegocio
from cuentas.models import Socio

from .models import Congelamiento, Membresia, Pago

Estado = Membresia.Estado
VIGENTES = [Estado.ACTIVA, Estado.CONGELADA]


def hoy():
    return timezone.localdate()


def fmt(fecha):
    return fecha.strftime('%d-%m-%Y')


def congelada_el(fecha):
    """Subconsulta: la membresía tiene un congelamiento que cubre esa fecha."""
    return Exists(Congelamiento.objects.filter(membresia=OuterRef('pk'), fecha_inicio__lte=fecha,
                                               fecha_fin__gt=fecha))


def sincronizar_estados(socio=None):
    """
    Pone al día los estados que dependen de la fecha: reactiva las
    congeladas cuyo congelamiento terminó y vence las que pasaron su fecha
    de término. Se llama antes de validar un acceso, reservar o listar, y
    cada noche con el comando actualizar_membresias. Son dos UPDATE.
    """
    dia = hoy()
    membresias = Membresia.objects.all() if socio is None else Membresia.objects.filter(socio=socio)
    reactivadas = membresias.filter(estado=Estado.CONGELADA).filter(~congelada_el(dia)).update(estado=Estado.ACTIVA)
    vencidas = membresias.filter(estado=Estado.ACTIVA, fecha_fin__lt=dia).update(estado=Estado.VENCIDA)
    return reactivadas, vencidas


def membresia_para(socio, fecha):
    """La membresía que deja entrar o reservar ese día (None si no hay)."""
    return (Membresia.objects
            .filter(socio=socio, estado__in=VIGENTES, fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
            .filter(~congelada_el(fecha)).select_related('plan').first())


def motivo_sin_membresia(socio, fecha):
    """(causa, texto) de por qué el socio no puede entrar o reservar ese día."""
    congelamiento = (Congelamiento.objects
                     .filter(membresia__socio=socio, membresia__estado__in=VIGENTES,
                             fecha_inicio__lte=fecha, fecha_fin__gt=fecha).first())
    if congelamiento:
        return 'CONGELADA', f'Membresía congelada hasta el {fmt(congelamiento.ultimo_dia)}.'
    futura = (Membresia.objects.filter(socio=socio, estado=Estado.ACTIVA, fecha_inicio__gt=fecha)
              .order_by('fecha_inicio').first())
    if futura:
        return 'POR_COMENZAR', f'Su membresía comienza el {fmt(futura.fecha_inicio)}.'
    ultima = (Membresia.objects.filter(socio=socio, fecha_fin__lt=fecha).exclude(estado=Estado.CANCELADA)
              .order_by('-fecha_fin').first())
    if ultima and ultima.fecha_fin >= hoy():
        return 'VENCE_ANTES', f'Su membresía termina el {fmt(ultima.fecha_fin)}, antes de esa fecha.'
    if ultima:
        return 'VENCIDA', f'Membresía vencida el {fmt(ultima.fecha_fin)}.'
    return 'SIN_MEMBRESIA', 'El socio no tiene una membresía vigente.'


def situacion(socio):
    """
    Resumen de la membresía del socio para las pantallas. Usa
    socio.membresias.all(), así aprovecha el prefetch de los listados.
    """
    dia = hoy()
    membresias = [m for m in socio.membresias.all() if m.estado != Estado.CANCELADA]
    actual = next((m for m in membresias if m.estado in VIGENTES and m.fecha_inicio <= dia <= m.fecha_fin), None)
    futuras = sorted((m for m in membresias if m.estado == Estado.ACTIVA and m.fecha_inicio > dia),
                     key=lambda m: m.fecha_inicio)
    if actual:
        estado, membresia = actual.estado, actual
    elif futuras:
        estado, membresia = 'POR_COMENZAR', futuras[0]
    elif membresias:
        estado, membresia = Estado.VENCIDA, max(membresias, key=lambda m: m.fecha_fin)
    else:
        return {'estado': 'SIN_MEMBRESIA', 'texto': 'Sin membresía', 'membresia_id': None, 'plan': None,
                'fecha_inicio': None, 'fecha_fin': None, 'dias_restantes': 0, 'renovada_hasta': None}
    textos = {**dict(Estado.choices), 'POR_COMENZAR': 'Por comenzar'}
    return {
        'estado': estado,
        'texto': textos[estado],
        'membresia_id': membresia.pk,
        'plan': membresia.plan.nombre,
        'fecha_inicio': membresia.fecha_inicio,
        'fecha_fin': membresia.fecha_fin,
        'dias_restantes': membresia.dias_restantes,
        # si pagó una renovación por adelantado, hasta cuándo queda cubierto
        'renovada_hasta': max(m.fecha_fin for m in futuras) if actual and futuras else None,
    }


@transaction.atomic
def registrar_pago(socio, plan, metodo, registrado_por=None, observacion='', pago=None):
    """
    Registra el pago de un plan y crea la membresía ACTIVA que paga.
    Si el socio ya tiene una membresía vigente (o una renovación pagada),
    la nueva parte el día siguiente al término: así no pierde días.
    """
    if not plan.activo:
        raise ErrorDeNegocio(f'El plan "{plan}" no está a la venta.')
    # bloqueo al socio: dos pagos al mismo tiempo no calculan la misma fecha de inicio
    socio = Socio.objects.select_for_update().get(pk=socio.pk)
    sincronizar_estados(socio)
    dia = hoy()
    ultimo_dia = (Membresia.objects.filter(socio=socio, estado__in=VIGENTES, fecha_fin__gte=dia)
                  .aggregate(m=Max('fecha_fin'))['m'])
    inicio = ultimo_dia + timedelta(days=1) if ultimo_dia else dia
    membresia = Membresia.objects.create(socio=socio, plan=plan, fecha_inicio=inicio,
                                         fecha_fin=inicio + timedelta(days=plan.duracion_dias - 1))
    pago = pago or Pago()
    pago.socio, pago.plan, pago.membresia, pago.monto = socio, plan, membresia, plan.precio
    pago.metodo, pago.registrado_por, pago.observacion = metodo, registrado_por, observacion
    pago.save()
    return pago


def _siguientes(membresia):
    """Membresías del socio que empiezan después de esta (renovaciones pagadas por adelantado)."""
    return list(Membresia.objects.select_for_update()
                .filter(socio_id=membresia.socio_id, fecha_inicio__gt=membresia.fecha_fin)
                .exclude(estado=Estado.CANCELADA))


def _correr(membresias, dias):
    """Mueve las fechas de esas membresías para que no se traslapen ni quede un hueco."""
    for m in membresias:
        m.fecha_inicio += timedelta(days=dias)
        m.fecha_fin += timedelta(days=dias)
        m.save(update_fields=['fecha_inicio', 'fecha_fin'])


@transaction.atomic
def congelar(membresia, dias, motivo='', registrado_por=None):
    """
    Congela la membresía desde hoy por `dias` días. Esos días se suman al
    término (no se pierden), mientras dure no puede entrar ni reservar, y se
    liberan sus cupos en las clases de esos días (pasa el siguiente de la
    lista de espera).
    """
    m = Membresia.objects.select_for_update().select_related('plan', 'socio').get(pk=membresia.pk)
    sincronizar_estados(m.socio)
    m.refresh_from_db(fields=['estado'])
    dia = hoy()
    if m.estado != Estado.ACTIVA or not m.fecha_inicio <= dia <= m.fecha_fin:
        raise Conflicto('Solo se puede congelar una membresía activa y vigente hoy.')
    if m.plan.dias_congelamiento == 0:
        raise ErrorDeNegocio(f'El plan "{m.plan}" no permite congelar la membresía.')
    disponibles = m.plan.dias_congelamiento - m.dias_congelados()
    if disponibles <= 0:
        raise ErrorDeNegocio(f'Ya usó los {m.plan.dias_congelamiento} días de congelamiento de su plan.')
    if not 1 <= dias <= disponibles:
        raise ErrorDeNegocio(f'Puede congelar entre 1 y {disponibles} días '
                             f'(su plan permite {m.plan.dias_congelamiento} en total).')

    siguientes = _siguientes(m)
    Congelamiento.objects.create(membresia=m, fecha_inicio=dia, fecha_fin=dia + timedelta(days=dias),
                                 motivo=motivo, registrado_por=registrado_por)
    m.fecha_fin += timedelta(days=dias)
    m.estado = Estado.CONGELADA
    m.save(update_fields=['fecha_fin', 'estado'])
    _correr(siguientes, dias)

    from clases.services import cancelar_reservas_sin_cobertura
    cancelar_reservas_sin_cobertura(m.socio, 'Membresía congelada')
    return m


@transaction.atomic
def descongelar(membresia):
    """Termina el congelamiento hoy. Los días que no alcanzó a usar se descuentan del término."""
    m = Membresia.objects.select_for_update().get(pk=membresia.pk)
    if m.estado != Estado.CONGELADA:
        raise Conflicto('La membresía no está congelada.')
    dia = hoy()
    congelamiento = m.congelamiento_vigente(dia)
    if congelamiento:
        no_usados = (congelamiento.fecha_fin - dia).days
        siguientes = _siguientes(m)
        congelamiento.fecha_fin = dia
        congelamiento.save(update_fields=['fecha_fin'])
        m.fecha_fin -= timedelta(days=no_usados)
        _correr(siguientes, -no_usados)
    m.estado = Estado.ACTIVA
    m.save(update_fields=['fecha_fin', 'estado'])
    return m


@transaction.atomic
def anular_pago(pago, motivo=''):
    """
    Anula el pago (no se borra: queda para auditoría) y cancela la
    membresía que pagaba. Las reservas que quedan sin membresía se liberan.
    """
    p = Pago.objects.select_for_update().select_related('membresia', 'socio').get(pk=pago.pk)
    if p.estado == Pago.Estado.ANULADO:
        raise Conflicto('El pago ya estaba anulado.')
    p.estado = Pago.Estado.ANULADO
    p.anulado_en = timezone.now()
    p.motivo_anulacion = motivo
    p.save(update_fields=['estado', 'anulado_en', 'motivo_anulacion'])
    p.membresia.estado = Estado.CANCELADA
    p.membresia.save(update_fields=['estado'])

    from clases.services import cancelar_reservas_sin_cobertura
    cancelar_reservas_sin_cobertura(p.socio, 'Pago anulado')
    return p


def validar_traslape(socio_id, inicio, fin, excluir_pk=None):
    """Una membresía (de cortesía o corregida a mano) no puede pisar otra del mismo socio."""
    choque = (Membresia.objects.filter(socio_id=socio_id, fecha_inicio__lte=fin, fecha_fin__gte=inicio)
              .exclude(pk=excluir_pk).exclude(estado=Estado.CANCELADA).first())
    if choque:
        raise ErrorDeNegocio(f'Se traslapa con otra membresía del socio '
                             f'({fmt(choque.fecha_inicio)} al {fmt(choque.fecha_fin)}).')
