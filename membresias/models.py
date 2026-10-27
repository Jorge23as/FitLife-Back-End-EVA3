"""
Modelos de la app membresias: Plan, Membresia, Congelamiento y Pago.

Plan 1─N Membresia N─1 Socio
Membresia 1─N Congelamiento
Membresia 1─1 Pago (el pago es el que crea la membresía, ver services.py)

Las reglas (cómo se calculan las fechas, cuándo vence o se congela) están
en services.py; acá solo la estructura de las tablas y cálculos simples.
"""
from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Plan(models.Model):
    nombre = models.CharField(max_length=60, unique=True)
    descripcion = models.TextField('descripción', blank=True)
    precio = models.PositiveIntegerField('precio (CLP)', validators=[MinValueValidator(1000)])
    duracion_dias = models.PositiveSmallIntegerField(
        'duración (días)', validators=[MinValueValidator(1), MaxValueValidator(730)])
    incluye_clases = models.BooleanField('incluye clases grupales', default=True)
    max_reservas_activas = models.PositiveSmallIntegerField(
        'máximo de reservas activas', null=True, blank=True,
        help_text='Cuántas clases futuras puede tener reservadas a la vez. Vacío = sin límite.')
    dias_congelamiento = models.PositiveSmallIntegerField(
        'días de congelamiento', default=0,
        help_text='Total de días que se puede congelar cada membresía de este plan (0 = no se puede).')
    activo = models.BooleanField('a la venta', default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'plan'
        verbose_name_plural = 'planes'
        ordering = ['precio']

    def __str__(self):
        return self.nombre


class Membresia(models.Model):

    class Estado(models.TextChoices):
        ACTIVA = 'ACTIVA', 'Activa'
        VENCIDA = 'VENCIDA', 'Vencida'
        CONGELADA = 'CONGELADA', 'Congelada'
        CANCELADA = 'CANCELADA', 'Cancelada (pago anulado)'

    # PROTECT: no se puede borrar un socio o un plan que tiene membresías (historial)
    socio = models.ForeignKey('cuentas.Socio', on_delete=models.PROTECT, related_name='membresias')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='membresias')
    fecha_inicio = models.DateField('inicio')
    fecha_fin = models.DateField('término', help_text='Último día en que la membresía permite entrar.')
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVA)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'membresía'
        verbose_name_plural = 'membresías'
        ordering = ['-fecha_inicio', '-id']
        indexes = [models.Index(fields=['socio', 'estado'])]
        constraints = [
            models.CheckConstraint(condition=Q(fecha_fin__gte=models.F('fecha_inicio')),
                                   name='ck_membresia_fechas'),
        ]

    def __str__(self):
        return f'{self.plan} · {self.socio.nombre} ({self.get_estado_display()})'

    @property
    def dias_restantes(self):
        """Días que le quedan contando hoy (0 si ya terminó)."""
        hoy = timezone.localdate()
        if self.fecha_fin < hoy:
            return 0
        return (self.fecha_fin - max(hoy, self.fecha_inicio)).days + 1

    def dias_congelados(self):
        return sum(c.dias for c in self.congelamientos.all())

    def congelamiento_vigente(self, fecha=None):
        fecha = fecha or timezone.localdate()
        return self.congelamientos.filter(fecha_inicio__lte=fecha, fecha_fin__gt=fecha).first()


# Pausa de una membresía. fecha_fin es el día en que se reactiva (no se
# cuenta como congelado): congelar 7 días desde el 1 deja fecha_fin = 8.
class Congelamiento(models.Model):
    membresia = models.ForeignKey(Membresia, on_delete=models.CASCADE, related_name='congelamientos')
    fecha_inicio = models.DateField('desde')
    fecha_fin = models.DateField('se reactiva el')
    motivo = models.CharField(max_length=200, blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'congelamiento'
        verbose_name_plural = 'congelamientos'
        ordering = ['-fecha_inicio']
        constraints = [
            models.CheckConstraint(condition=Q(fecha_fin__gte=models.F('fecha_inicio')),
                                   name='ck_congelamiento_fechas'),
        ]

    @property
    def dias(self):
        return (self.fecha_fin - self.fecha_inicio).days

    @property
    def ultimo_dia(self):
        return self.fecha_fin - timedelta(days=1)

    def __str__(self):
        return f'{self.dias} días desde {self.fecha_inicio:%d-%m-%Y}'


class Pago(models.Model):

    class Metodo(models.TextChoices):
        EFECTIVO = 'EFECTIVO', 'Efectivo'
        DEBITO = 'DEBITO', 'Tarjeta de débito'
        CREDITO = 'CREDITO', 'Tarjeta de crédito'
        TRANSFERENCIA = 'TRANSFERENCIA', 'Transferencia'

    class Estado(models.TextChoices):
        PAGADO = 'PAGADO', 'Pagado'
        ANULADO = 'ANULADO', 'Anulado'

    socio = models.ForeignKey('cuentas.Socio', on_delete=models.PROTECT, related_name='pagos')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='pagos')
    # cada pago crea una membresía; PROTECT: no se borra una membresía pagada (se anula el pago)
    membresia = models.OneToOneField(Membresia, on_delete=models.PROTECT, related_name='pago')
    # el precio se copia al pagar: si después cambia el plan, el pago no cambia
    monto = models.PositiveIntegerField('monto (CLP)')
    metodo = models.CharField('método', max_length=15, choices=Metodo.choices)
    estado = models.CharField(max_length=8, choices=Estado.choices, default=Estado.PAGADO)
    fecha = models.DateTimeField(default=timezone.now)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='pagos_registrados')
    observacion = models.CharField('observación', max_length=200, blank=True)
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField('motivo de anulación', max_length=200, blank=True)

    class Meta:
        verbose_name = 'pago'
        verbose_name_plural = 'pagos'
        ordering = ['-fecha', '-id']

    @property
    def comprobante(self):
        return f'FL-{self.pk:06d}' if self.pk else ''

    def __str__(self):
        return f'{self.comprobante} · {self.socio.nombre} · ${self.monto:,}'.replace(',', '.')
