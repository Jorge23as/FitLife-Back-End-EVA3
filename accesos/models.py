"""
Modelos de la app accesos: Sede, Visita y RegistroAcceso.

Sede 1─N Visita N─1 Socio
Sede 1─N RegistroAcceso N─1 Socio (puede ser null si el QR no era válido)

- RegistroAcceso: cada lectura de QR en la entrada, permitida o denegada,
  con su causa. Es el historial de auditoría: no se edita.
- Visita: la estadía de un socio dentro del gimnasio. La entrada la abre y
  la salida la cierra. El aforo en tiempo real es la cantidad de visitas
  abiertas (sin hora de salida).
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Sede(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    direccion = models.CharField('dirección', max_length=150)
    aforo_maximo = models.PositiveIntegerField('aforo máximo', validators=[MinValueValidator(1)],
                                               help_text='Personas que pueden estar dentro al mismo tiempo.')
    hora_apertura = models.TimeField('abre a las')
    hora_cierre = models.TimeField('cierra a las')
    horas_max_permanencia = models.PositiveSmallIntegerField(
        'horas máximas de permanencia', default=4, validators=[MinValueValidator(1)],
        help_text='Si alguien no marca su salida, su visita se cierra sola pasado este tiempo.')
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'sede'
        verbose_name_plural = 'sedes'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    def abierta(self, momento=None):
        hora = timezone.localtime(momento or timezone.now()).time()
        if self.hora_apertura == self.hora_cierre:      # abierta las 24 horas
            return True
        if self.hora_apertura < self.hora_cierre:
            return self.hora_apertura <= hora < self.hora_cierre
        return hora >= self.hora_apertura or hora < self.hora_cierre  # cierra después de medianoche


class Visita(models.Model):
    socio = models.ForeignKey('cuentas.Socio', on_delete=models.CASCADE, related_name='visitas')
    sede = models.ForeignKey(Sede, on_delete=models.PROTECT, related_name='visitas')
    entrada = models.DateTimeField(default=timezone.now, db_index=True)
    salida = models.DateTimeField(null=True, blank=True)
    cierre_automatico = models.BooleanField(
        default=False, help_text='La cerró el sistema porque el socio no marcó su salida.')

    class Meta:
        verbose_name = 'visita'
        verbose_name_plural = 'visitas'
        ordering = ['-entrada']
        constraints = [
            # un socio no puede estar "dentro" dos veces (anti-passback)
            models.UniqueConstraint(fields=['socio'], condition=Q(salida__isnull=True), name='uq_visita_abierta'),
            models.CheckConstraint(condition=Q(salida__isnull=True) | Q(salida__gte=models.F('entrada')),
                                   name='ck_visita_horario'),
        ]

    def __str__(self):
        return f'{self.socio.nombre} · {timezone.localtime(self.entrada):%d-%m %H:%M}'

    @property
    def minutos(self):
        fin = self.salida or timezone.now()
        return int((fin - self.entrada).total_seconds() // 60)


class RegistroAcceso(models.Model):

    class Tipo(models.TextChoices):
        ENTRADA = 'ENTRADA', 'Entrada'
        SALIDA = 'SALIDA', 'Salida'

    class Resultado(models.TextChoices):
        PERMITIDO = 'PERMITIDO', 'Permitido'
        DENEGADO = 'DENEGADO', 'Denegado'

    class Causa(models.TextChoices):
        OK = 'OK', 'Acceso correcto'
        QR_INVALIDO = 'QR_INVALIDO', 'QR no válido'
        QR_EXPIRADO = 'QR_EXPIRADO', 'QR expirado'
        SOCIO_INACTIVO = 'SOCIO_INACTIVO', 'Cuenta desactivada'
        SIN_MEMBRESIA = 'SIN_MEMBRESIA', 'Sin membresía'
        VENCIDA = 'VENCIDA', 'Membresía vencida'
        CONGELADA = 'CONGELADA', 'Membresía congelada'
        POR_COMENZAR = 'POR_COMENZAR', 'Membresía aún no comienza'
        FUERA_HORARIO = 'FUERA_HORARIO', 'Fuera de horario'
        AFORO_COMPLETO = 'AFORO_COMPLETO', 'Aforo completo'
        YA_DENTRO = 'YA_DENTRO', 'Ya estaba dentro'
        SIN_ENTRADA = 'SIN_ENTRADA', 'Salida sin entrada'

    class Metodo(models.TextChoices):
        CAMARA = 'CAMARA', 'Lector QR (cámara)'
        SIMULADO = 'SIMULADO', 'Simulación de QR'
        MANUAL = 'MANUAL', 'Código ingresado a mano'

    sede = models.ForeignKey(Sede, on_delete=models.PROTECT, related_name='registros')
    socio = models.ForeignKey('cuentas.Socio', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='accesos')
    visita = models.ForeignKey(Visita, on_delete=models.SET_NULL, null=True, blank=True, related_name='registros')
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    resultado = models.CharField(max_length=9, choices=Resultado.choices)
    causa = models.CharField(max_length=15, choices=Causa.choices)
    motivo = models.CharField(max_length=200, blank=True)
    metodo = models.CharField('método', max_length=8, choices=Metodo.choices)
    # lo leído cuando el QR no sirve (recortado), para revisar intentos raros
    codigo_leido = models.CharField('código leído', max_length=120, blank=True)
    fecha_hora = models.DateTimeField(default=timezone.now, db_index=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')

    class Meta:
        verbose_name = 'registro de acceso'
        verbose_name_plural = 'registros de acceso'
        ordering = ['-fecha_hora', '-id']

    def __str__(self):
        quien = self.socio.nombre if self.socio else 'QR desconocido'
        return f'{self.get_tipo_display()} {self.get_resultado_display().lower()} · {quien}'
