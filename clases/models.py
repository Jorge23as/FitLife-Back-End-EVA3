"""
Modelos de la app clases: Actividad, Sala, Clase y Reserva.

Actividad 1─N Clase N─1 Sala N─1 Sede
Instructor 1─N Clase 1─N Reserva N─1 Socio

Una Clase es una sesión concreta (Spinning del lunes a las 19:00). Su cupo
no puede superar la capacidad de la sala. Las reservas que no alcanzan
cupo quedan EN ESPERA y suben solas cuando alguien cancela (services.py).
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Actividad(models.Model):

    class Intensidad(models.TextChoices):
        BAJA = 'BAJA', 'Baja'
        MEDIA = 'MEDIA', 'Media'
        ALTA = 'ALTA', 'Alta'

    nombre = models.CharField(max_length=60, unique=True)
    descripcion = models.TextField('descripción', blank=True)
    duracion_minutos = models.PositiveSmallIntegerField('duración (minutos)', default=60,
                                                        validators=[MinValueValidator(15)])
    intensidad = models.CharField(max_length=5, choices=Intensidad.choices, default=Intensidad.MEDIA)
    color = models.CharField(max_length=7, default='#f97316', help_text='Color en el horario, formato #RRGGBB',
                             validators=[RegexValidator(r'^#[0-9a-fA-F]{6}$', 'Use el formato #RRGGBB.')])
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'actividad'
        verbose_name_plural = 'actividades'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Sala(models.Model):
    sede = models.ForeignKey('accesos.Sede', on_delete=models.PROTECT, related_name='salas')
    nombre = models.CharField(max_length=60)
    capacidad = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)],
                                                 help_text='Personas que caben en la sala.')

    class Meta:
        verbose_name = 'sala'
        verbose_name_plural = 'salas'
        ordering = ['nombre']
        constraints = [models.UniqueConstraint(fields=['sede', 'nombre'], name='uq_sala_por_sede')]

    def __str__(self):
        return f'{self.nombre} ({self.capacidad} personas)'


class Clase(models.Model):

    class Estado(models.TextChoices):
        PROGRAMADA = 'PROGRAMADA', 'Programada'
        CANCELADA = 'CANCELADA', 'Cancelada'

    actividad = models.ForeignKey(Actividad, on_delete=models.PROTECT, related_name='clases')
    instructor = models.ForeignKey('cuentas.Instructor', on_delete=models.PROTECT, related_name='clases')
    sala = models.ForeignKey(Sala, on_delete=models.PROTECT, related_name='clases')
    inicio = models.DateTimeField(db_index=True)
    fin = models.DateTimeField(blank=True, help_text='Si se deja vacío, inicio + duración de la actividad.')
    cupo = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)],
                                            help_text='No puede superar la capacidad de la sala.')
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PROGRAMADA)

    class Meta:
        verbose_name = 'clase'
        verbose_name_plural = 'clases'
        ordering = ['inicio']
        constraints = [models.CheckConstraint(condition=Q(fin__gt=models.F('inicio')), name='ck_clase_horario')]

    def __str__(self):
        return f'{self.actividad} {timezone.localtime(self.inicio):%d-%m %H:%M}'

    @property
    def fecha(self):
        return timezone.localtime(self.inicio).date()

    def save(self, *args, **kwargs):
        if self.inicio and not self.fin:
            self.fin = self.inicio + timedelta(minutes=self.actividad.duracion_minutos)
        super().save(*args, **kwargs)

    def ocupados(self):
        return self.reservas.filter(estado__in=Reserva.OCUPAN_CUPO).count()

    def clean(self):
        """Reglas de la clase. Las usa el formulario del admin y el serializer de la API."""
        if self.inicio and not self.fin and self.actividad_id:
            self.fin = self.inicio + timedelta(minutes=self.actividad.duracion_minutos)
        errores = {}
        if self.inicio and self.fin and self.fin <= self.inicio:
            errores['fin'] = 'El término debe ser posterior al inicio.'
        if self.sala_id and self.cupo and self.cupo > self.sala.capacidad:
            errores['cupo'] = f'El cupo no puede superar la capacidad de la sala ({self.sala.capacidad}).'
        if self.pk and self.cupo is not None:
            ocupados = self.ocupados()
            if self.cupo < ocupados:
                errores['cupo'] = f'Ya hay {ocupados} reservas confirmadas: el cupo no puede ser menor.'
        if self.inicio and self.fin and self.estado == self.Estado.PROGRAMADA:
            cruce = (Clase.objects.filter(estado=self.Estado.PROGRAMADA, inicio__lt=self.fin, fin__gt=self.inicio)
                     .exclude(pk=self.pk))
            if self.sala_id and cruce.filter(sala_id=self.sala_id).exists():
                errores['sala'] = 'La sala ya tiene otra clase en ese horario.'
            if self.instructor_id and cruce.filter(instructor_id=self.instructor_id).exists():
                errores['instructor'] = 'El instructor ya tiene otra clase en ese horario.'
        if errores:
            raise ValidationError(errores)


class Reserva(models.Model):

    class Estado(models.TextChoices):
        CONFIRMADA = 'CONFIRMADA', 'Confirmada'
        ESPERA = 'ESPERA', 'En lista de espera'
        CANCELADA = 'CANCELADA', 'Cancelada'
        ASISTIO = 'ASISTIO', 'Asistió'
        AUSENTE = 'AUSENTE', 'No asistió'

    # estados que ocupan un cupo de la clase
    OCUPAN_CUPO = [Estado.CONFIRMADA, Estado.ASISTIO, Estado.AUSENTE]
    # estados que se pueden cancelar (antes de que empiece la clase)
    ACTIVAS = [Estado.CONFIRMADA, Estado.ESPERA]

    socio = models.ForeignKey('cuentas.Socio', on_delete=models.CASCADE, related_name='reservas')
    clase = models.ForeignKey(Clase, on_delete=models.CASCADE, related_name='reservas')
    estado = models.CharField(max_length=10, choices=Estado.choices)
    creada_en = models.DateTimeField(auto_now_add=True)
    # cuándo pasó de la lista de espera a confirmada (para avisarle al socio)
    promovida_en = models.DateTimeField(null=True, blank=True)
    cancelada_en = models.DateTimeField(null=True, blank=True)
    motivo_cancelacion = models.CharField('motivo de cancelación', max_length=120, blank=True)

    class Meta:
        verbose_name = 'reserva'
        verbose_name_plural = 'reservas'
        ordering = ['creada_en', 'id']
        constraints = [
            # un socio no puede tener dos reservas vigentes en la misma clase (las canceladas no cuentan)
            models.UniqueConstraint(fields=['socio', 'clase'], condition=~Q(estado='CANCELADA'),
                                    name='uq_reserva_vigente'),
        ]

    def __str__(self):
        return f'{self.socio.nombre} · {self.clase} ({self.get_estado_display()})'

    def posicion_espera(self):
        """Lugar en la lista de espera (1 = el siguiente en entrar)."""
        if self.estado != self.Estado.ESPERA:
            return None
        return self.clase.reservas.filter(
            Q(creada_en__lt=self.creada_en) | Q(creada_en=self.creada_en, id__lt=self.id),
            estado=self.Estado.ESPERA,
        ).count() + 1
