"""
Admin de actividades, salas, clases y reservas.

La ocupación de cada clase se ve como barra en la lista. Las acciones
(cancelar, repetir la semana siguiente, cancelar reservas) y el guardado
pasan por services.py: al subir el cupo de una clase, entra solo la gente
de la lista de espera.
"""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.html import format_html

from core.admin_utils import badge, barra
from core.excepciones import ErrorDeNegocio

from . import services
from .models import Actividad, Clase, Reserva, Sala


@admin.register(Actividad)
class ActividadAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'muestra_color', 'duracion_minutos', 'intensidad', 'activa']
    list_editable = ['activa']
    list_filter = ['intensidad', 'activa']
    search_fields = ['nombre']

    @admin.display(description='color')
    def muestra_color(self, obj):
        return format_html('<span class="fl-color" style="background:{}"></span> {}', obj.color, obj.color)


@admin.register(Sala)
class SalaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'sede', 'capacidad']
    list_filter = ['sede']
    search_fields = ['nombre']


class MomentoFiltro(admin.SimpleListFilter):
    title = 'momento'
    parameter_name = 'momento'

    def lookups(self, request, model_admin):
        return [('proximas', 'Próximas'), ('en_curso', 'En curso'), ('hoy', 'Hoy'), ('pasadas', 'Finalizadas')]

    def queryset(self, request, queryset):
        ahora = timezone.now()
        filtros = {
            'proximas': Q(inicio__gt=ahora),
            'en_curso': Q(inicio__lte=ahora, fin__gt=ahora),
            'hoy': Q(inicio__date=timezone.localdate()),
            'pasadas': Q(fin__lte=ahora),
        }
        return queryset.filter(filtros[self.value()]) if self.value() in filtros else queryset


class ReservaInline(admin.TabularInline):
    model = Reserva
    extra = 0
    can_delete = False
    fields = ['socio', 'estado_etiqueta', 'posicion', 'creada_en', 'promovida_en']
    readonly_fields = fields
    ordering = ['estado', 'creada_en']
    verbose_name_plural = 'reservas (confirmadas y lista de espera)'

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(estado=Reserva.Estado.CANCELADA).select_related('socio__usuario')

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description='estado')
    def estado_etiqueta(self, obj):
        return badge(obj.estado, obj.get_estado_display())

    @admin.display(description='lugar en espera')
    def posicion(self, obj):
        return obj.posicion_espera() or '-'


@admin.register(Clase)
class ClaseAdmin(admin.ModelAdmin):
    list_display = ['actividad', 'inicio', 'sala', 'instructor', 'ocupacion', 'en_espera', 'estado_etiqueta']
    list_filter = [MomentoFiltro, 'estado', 'actividad', 'sala', 'instructor', 'inicio']
    search_fields = ['actividad__nombre', 'instructor__usuario__first_name', 'instructor__usuario__last_name',
                     'sala__nombre']
    date_hierarchy = 'inicio'
    list_select_related = ['actividad', 'sala', 'instructor__usuario']
    list_per_page = 30
    fields = ['actividad', 'instructor', 'sala', 'inicio', 'fin', 'cupo', 'estado']
    readonly_fields = ['estado']
    inlines = [ReservaInline]
    actions = ['cancelar_clases', 'repetir_semana_siguiente']

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            n_ocupados=Count('reservas', filter=Q(reservas__estado__in=Reserva.OCUPAN_CUPO)),
            n_espera=Count('reservas', filter=Q(reservas__estado=Reserva.Estado.ESPERA)))

    def save_model(self, request, obj, form, change):
        # mismo guardado que la API: si subió el cupo, entra gente de la lista de espera
        promovidas = services.guardar_clase(obj)
        if promovidas:
            nombres = ', '.join(r.socio.nombre for r in promovidas)
            self.message_user(request, f'Subieron de la lista de espera: {nombres}.', messages.INFO)

    @admin.display(description='ocupación', ordering='n_ocupados')
    def ocupacion(self, obj):
        return barra(obj.n_ocupados, obj.cupo)

    @admin.display(description='en espera', ordering='n_espera')
    def en_espera(self, obj):
        return obj.n_espera or '-'

    @admin.display(description='estado', ordering='estado')
    def estado_etiqueta(self, obj):
        return badge(obj.estado, obj.get_estado_display())

    @admin.action(description='Cancelar las clases seleccionadas (y sus reservas)', permissions=['change'])
    def cancelar_clases(self, request, queryset):
        for clase in queryset:
            try:
                canceladas = services.cancelar_clase(clase)
                self.message_user(request, f'{clase}: cancelada ({canceladas} reservas canceladas).', messages.SUCCESS)
            except ErrorDeNegocio as e:
                self.message_user(request, f'{clase}: {e.mensaje}', messages.ERROR)

    @admin.action(description='Repetir la semana siguiente (mismo horario)', permissions=['add'])
    def repetir_semana_siguiente(self, request, queryset):
        for clase in queryset:
            try:
                copia = services.repetir_semana_siguiente(clase)
                self.message_user(request, f'Creada: {copia}.', messages.SUCCESS)
            except ValidationError as e:
                self.message_user(request, f'{clase}: {" ".join(e.messages)}', messages.ERROR)


class ReservaForm(forms.ModelForm):
    """Reservar desde el admin: las mismas reglas que en el sitio (membresía, cupo, choque de horario...)."""
    class Meta:
        model = Reserva
        fields = ['socio', 'clase']

    def clean(self):
        datos = super().clean()
        if datos.get('socio') and datos.get('clase'):
            try:
                services.validar_reserva(datos['socio'], datos['clase'])
            except ErrorDeNegocio as e:
                raise ValidationError(e.mensaje)
        return datos


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    form = ReservaForm
    list_display = ['socio', 'clase', 'estado_etiqueta', 'posicion', 'creada_en', 'promovida_en']
    list_filter = ['estado', 'clase__actividad', 'clase__inicio']
    search_fields = ['socio__usuario__first_name', 'socio__usuario__last_name', 'socio__usuario__rut',
                     'clase__actividad__nombre']
    autocomplete_fields = ['socio', 'clase']
    list_select_related = ['socio__usuario', 'clase__actividad']
    list_per_page = 30
    actions = ['cancelar', 'marcar_asistio', 'marcar_ausente']

    def get_fields(self, request, obj=None):
        if obj is None:
            return ['socio', 'clase']
        return ['socio', 'clase', 'estado', 'creada_en', 'promovida_en', 'cancelada_en', 'motivo_cancelacion']

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        return self.get_fields(request, obj)  # una reserva cambia solo con las acciones

    def save_model(self, request, obj, form, change):
        if not change:
            services.reservar(obj.socio, obj.clase, reserva=obj)
            if obj.estado == Reserva.Estado.ESPERA:
                self.message_user(request, f'La clase está llena: quedó en lista de espera (lugar '
                                           f'{obj.posicion_espera()}).', messages.WARNING)

    @admin.display(description='estado', ordering='estado')
    def estado_etiqueta(self, obj):
        return badge(obj.estado, obj.get_estado_display())

    @admin.display(description='lugar en espera')
    def posicion(self, obj):
        return obj.posicion_espera() or '-'

    @admin.action(description='Cancelar (sube el primero de la lista de espera)', permissions=['change'])
    def cancelar(self, request, queryset):
        for reserva in queryset:
            try:
                _, promovidas = services.cancelar_reserva(reserva, 'Cancelada por recepción')
                extra = f' Subió: {promovidas[0].socio.nombre}.' if promovidas else ''
                self.message_user(request, f'{reserva.socio.nombre}: reserva cancelada.{extra}', messages.SUCCESS)
            except ErrorDeNegocio as e:
                self.message_user(request, f'{reserva.socio.nombre}: {e.mensaje}', messages.ERROR)

    def _asistencia(self, request, queryset, asistio):
        for reserva in queryset:
            try:
                services.marcar_asistencia(reserva, asistio)
            except ErrorDeNegocio as e:
                self.message_user(request, f'{reserva.socio.nombre}: {e.mensaje}', messages.ERROR)

    @admin.action(description='Marcar asistió', permissions=['change'])
    def marcar_asistio(self, request, queryset):
        self._asistencia(request, queryset, True)

    @admin.action(description='Marcar no asistió', permissions=['change'])
    def marcar_ausente(self, request, queryset):
        self._asistencia(request, queryset, False)
