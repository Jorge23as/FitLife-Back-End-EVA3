"""
Control de acceso con QR y aforo en tiempo real.

validar_acceso() es lo que pasa cuando recepción lee el QR de un socio:
  1. Verifica el QR (firma y 60 s de vigencia, ver qr.py).
  2. Decide si es ENTRADA o SALIDA: si el socio ya está dentro, la
     lectura es su salida (modo automático, como un torniquete).
  3. La SALIDA siempre se permite: cierra su visita.
  4. La ENTRADA se permite solo si:
       - el socio no está ya dentro (anti-passback: el QR no se puede
         pasar a otra persona para que entre también),
       - la sede está en horario,
       - tiene una membresía ACTIVA para hoy (no vencida ni congelada),
       - no se llenó el aforo máximo de la sede.
  5. Todo intento, permitido o denegado, queda en RegistroAcceso.

Se bloquea la fila de la sede (select_for_update): dos lecturas al mismo
tiempo no pueden pasar las dos con el último lugar del aforo.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import ExtractHour
from django.utils import timezone

from clases.models import Clase, Reserva
from cuentas.models import Socio
from membresias.services import membresia_para, motivo_sin_membresia, sincronizar_estados

from . import qr
from .models import RegistroAcceso, Sede, Visita

Tipo = RegistroAcceso.Tipo
Resultado = RegistroAcceso.Resultado
Causa = RegistroAcceso.Causa


def cerrar_visitas_vencidas(sede):
    """Cierra las visitas de quienes no marcaron salida pasado el máximo de permanencia."""
    limite = timedelta(hours=sede.horas_max_permanencia)
    vencidas = Visita.objects.filter(sede=sede, salida__isnull=True, entrada__lt=timezone.now() - limite)
    return vencidas.update(salida=F('entrada') + limite, cierre_automatico=True)


def nivel_aforo(porcentaje):
    if porcentaje >= 100:
        return 'COMPLETO'
    if porcentaje >= 80:
        return 'ALTO'
    if porcentaje >= 50:
        return 'MEDIO'
    return 'BAJO'


def estado_aforo(sede):
    cerrar_visitas_vencidas(sede)
    actual = Visita.objects.filter(sede=sede, salida__isnull=True).count()
    porcentaje = round(actual * 100 / sede.aforo_maximo) if sede.aforo_maximo else 0
    return {
        'actual': actual,
        'maximo': sede.aforo_maximo,
        'disponibles': max(sede.aforo_maximo - actual, 0),
        'porcentaje': porcentaje,
        'nivel': nivel_aforo(porcentaje),
    }


def sede_principal():
    return Sede.objects.filter(activa=True).order_by('id').first()


def _clase_de_hoy(socio):
    """La próxima clase reservada del socio para hoy (para mostrarla en recepción)."""
    ahora = timezone.now()
    fin_del_dia = timezone.localtime(ahora).replace(hour=23, minute=59, second=59)
    return (Reserva.objects.filter(socio=socio, estado__in=Reserva.ACTIVAS, clase__estado=Clase.Estado.PROGRAMADA,
                                   clase__fin__gt=ahora, clase__inicio__lte=fin_del_dia)
            .select_related('clase__actividad', 'clase__sala').order_by('clase__inicio').first())


@transaction.atomic
def validar_acceso(codigo, sede, metodo, registrado_por=None, modo='AUTO'):
    """Valida una lectura de QR y devuelve (registro, visita, membresia, reserva_de_hoy)."""
    sede = Sede.objects.select_for_update().get(pk=sede.pk)
    ahora = timezone.now()
    registro = RegistroAcceso(sede=sede, metodo=metodo, registrado_por=registrado_por, fecha_hora=ahora,
                              tipo=Tipo.SALIDA if modo == Tipo.SALIDA else Tipo.ENTRADA)

    def terminar(causa, motivo, resultado=Resultado.DENEGADO, visita=None, membresia=None):
        registro.causa, registro.motivo, registro.resultado, registro.visita = causa, motivo, resultado, visita
        if resultado == Resultado.DENEGADO and registro.socio is None:
            registro.codigo_leido = (codigo or '')[:120]
        registro.save()
        reserva = _clase_de_hoy(registro.socio) if registro.socio and resultado == Resultado.PERMITIDO else None
        return registro, visita, membresia, reserva

    # 1. el QR
    try:
        codigo_qr = qr.leer_token(codigo)
        socio = Socio.objects.select_for_update(of=('self',)).select_related('usuario').get(codigo_qr=codigo_qr)
    except qr.QrInvalido as e:
        return terminar(e.causa, e.motivo)
    except Socio.DoesNotExist:
        return terminar(Causa.QR_INVALIDO, 'El QR no corresponde a ningún socio (pudo ser regenerado).')
    registro.socio = socio
    if not socio.usuario.is_active:
        return terminar(Causa.SOCIO_INACTIVO, 'La cuenta del socio está desactivada.')

    # 2. entrada o salida
    cerrar_visitas_vencidas(sede)
    abierta = Visita.objects.filter(socio=socio, salida__isnull=True).first()
    if modo == 'AUTO':
        registro.tipo = Tipo.SALIDA if abierta else Tipo.ENTRADA

    # 3. salida
    if registro.tipo == Tipo.SALIDA:
        if not abierta:
            return terminar(Causa.SIN_ENTRADA, 'El socio no tiene una entrada registrada.')
        abierta.salida = ahora
        abierta.save(update_fields=['salida'])
        return terminar(Causa.OK, f'Salida registrada ({abierta.minutos} min dentro).', Resultado.PERMITIDO, abierta)

    # 4. entrada
    if abierta:
        return terminar(Causa.YA_DENTRO, 'El socio ya está dentro: debe marcar su salida antes de volver a entrar.')
    if not sede.abierta(ahora):
        return terminar(Causa.FUERA_HORARIO, f'Fuera de horario: la sede atiende de '
                                             f'{sede.hora_apertura:%H:%M} a {sede.hora_cierre:%H:%M}.')
    sincronizar_estados(socio)
    membresia = membresia_para(socio, timezone.localdate())
    if membresia is None:
        return terminar(*motivo_sin_membresia(socio, timezone.localdate()))
    dentro = Visita.objects.filter(sede=sede, salida__isnull=True).count()
    if dentro >= sede.aforo_maximo:
        return terminar(Causa.AFORO_COMPLETO, f'Aforo completo ({dentro}/{sede.aforo_maximo} personas).',
                        membresia=membresia)
    visita = Visita.objects.create(socio=socio, sede=sede, entrada=ahora)
    return terminar(Causa.OK, 'Entrada registrada.', Resultado.PERMITIDO, visita, membresia)


@transaction.atomic
def registrar_salida_manual(visita, registrado_por=None):
    """Recepción marca la salida de alguien que se fue sin pasar su QR (queda en el historial)."""
    visita = Visita.objects.select_for_update().get(pk=visita.pk)
    if visita.salida:
        return visita
    visita.salida = timezone.now()
    visita.save(update_fields=['salida'])
    RegistroAcceso.objects.create(sede=visita.sede, socio=visita.socio, visita=visita, tipo=Tipo.SALIDA,
                                  resultado=Resultado.PERMITIDO, causa=Causa.OK, metodo=RegistroAcceso.Metodo.MANUAL,
                                  motivo='Salida marcada por recepción.', registrado_por=registrado_por)
    return visita


def panel_aforo(sede):
    """Todos los datos del dashboard de aforo (lo pide la página cada 5 segundos)."""
    ahora = timezone.now()
    inicio_dia = timezone.localtime(ahora).replace(hour=0, minute=0, second=0, microsecond=0)
    aforo = estado_aforo(sede)

    dentro = (Visita.objects.filter(sede=sede, salida__isnull=True)
              .select_related('socio__usuario').order_by('entrada'))
    registros_hoy = RegistroAcceso.objects.filter(sede=sede, fecha_hora__gte=inicio_dia)
    totales = registros_hoy.aggregate(
        entradas=Count('id', filter=Q(tipo=Tipo.ENTRADA, resultado=Resultado.PERMITIDO)),
        salidas=Count('id', filter=Q(tipo=Tipo.SALIDA, resultado=Resultado.PERMITIDO)),
        denegados=Count('id', filter=Q(resultado=Resultado.DENEGADO)),
        socios=Count('socio', filter=Q(tipo=Tipo.ENTRADA, resultado=Resultado.PERMITIDO), distinct=True),
    )
    permanencia = (Visita.objects.filter(sede=sede, entrada__gte=inicio_dia, salida__isnull=False)
                   .aggregate(p=Avg(ExpressionWrapper(F('salida') - F('entrada'), output_field=DurationField())))['p'])
    por_hora = dict(registros_hoy.filter(tipo=Tipo.ENTRADA, resultado=Resultado.PERMITIDO)
                    .annotate(h=ExtractHour('fecha_hora')).values_list('h').annotate(n=Count('id')))
    hora_actual = timezone.localtime(ahora).hour
    desde = min([sede.hora_apertura.hour, *por_hora.keys()]) if por_hora else sede.hora_apertura.hour
    causas = dict(RegistroAcceso.Causa.choices)
    denegados = (registros_hoy.filter(resultado=Resultado.DENEGADO).values('causa')
                 .annotate(n=Count('id')).order_by('-n'))

    clases_hoy = (Clase.objects.filter(sala__sede=sede, estado=Clase.Estado.PROGRAMADA,
                                       inicio__gte=inicio_dia, inicio__lt=inicio_dia + timedelta(days=1), fin__gt=ahora)
                  .select_related('actividad', 'sala', 'instructor__usuario')
                  .annotate(n_ocupados=Count('reservas', filter=Q(reservas__estado__in=Reserva.OCUPAN_CUPO)),
                            n_espera=Count('reservas', filter=Q(reservas__estado=Reserva.Estado.ESPERA)))
                  .order_by('inicio'))

    def clase_json(c):
        return {'id': c.id, 'actividad': c.actividad.nombre, 'color': c.actividad.color, 'sala': c.sala.nombre,
                'instructor': c.instructor.nombre, 'inicio': c.inicio, 'fin': c.fin, 'cupo': c.cupo,
                'ocupados': c.n_ocupados, 'espera': c.n_espera}

    ultimos = registros_hoy.select_related('socio__usuario').order_by('-fecha_hora', '-id')[:12]
    return {
        'sede': {'id': sede.id, 'nombre': sede.nombre, 'hora_apertura': sede.hora_apertura,
                 'hora_cierre': sede.hora_cierre, 'abierta': sede.abierta(ahora)},
        **aforo,
        'actualizado': ahora,
        'dentro': [{'visita': v.id, 'socio': v.socio_id, 'nombre': v.socio.nombre, 'entrada': v.entrada,
                    'minutos': v.minutos} for v in dentro],
        'hoy': {**totales, 'permanencia_promedio_min': int(permanencia.total_seconds() // 60) if permanencia else None},
        'por_hora': [{'hora': h, 'entradas': por_hora.get(h, 0)} for h in range(desde, max(hora_actual, desde) + 1)],
        'denegados_por_causa': [{'causa': d['causa'], 'texto': causas.get(d['causa'], d['causa']), 'cantidad': d['n']}
                                for d in denegados],
        'clases_en_curso': [clase_json(c) for c in clases_hoy if c.inicio <= ahora],
        'proximas_clases': [clase_json(c) for c in clases_hoy if c.inicio > ahora][:6],
        'ultimos_eventos': [{'id': r.id, 'hora': r.fecha_hora, 'socio': r.socio.nombre if r.socio else None,
                             'tipo': r.tipo, 'resultado': r.resultado, 'causa': r.causa, 'motivo': r.motivo,
                             'metodo': r.metodo} for r in ultimos],
    }
