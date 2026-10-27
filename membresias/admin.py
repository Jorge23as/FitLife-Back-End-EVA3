"""
Admin de planes, membresías, congelamientos y pagos.

Las acciones del admin (congelar, descongelar, anular un pago, registrar
un pago) llaman a services.py: las mismas reglas que usa la API.
"""
from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.template.response import TemplateResponse
from django.utils import timezone

from core.admin_utils import badge, pesos
from core.excepciones import ErrorDeNegocio

from . import services
from .models import Congelamiento, Membresia, Pago, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'precio_clp', 'duracion_dias', 'incluye_clases', 'max_reservas_activas',
                    'dias_congelamiento', 'vigentes', 'activo']
    list_editable = ['activo']
    list_filter = ['activo', 'incluye_clases']
    search_fields = ['nombre']
    fieldsets = (
        (None, {'fields': ('nombre', 'descripcion', 'activo')}),
        ('Precio y duración', {'fields': ('precio', 'duracion_dias')}),
        ('Reglas del plan', {'fields': ('incluye_clases', 'max_reservas_activas', 'dias_congelamiento')}),
    )

    def get_queryset(self, request):
        hoy = timezone.localdate()
        return super().get_queryset(request).annotate(n_vigentes=Count(
            'membresias', filter=Q(membresias__estado__in=services.VIGENTES, membresias__fecha_fin__gte=hoy)))

    @admin.display(description='precio', ordering='precio')
    def precio_clp(self, obj):
        return pesos(obj.precio)

    @admin.display(description='membresías vigentes', ordering='n_vigentes')
    def vigentes(self, obj):
        return obj.n_vigentes


class PorVencerFiltro(admin.SimpleListFilter):
    title = 'vencimiento'
    parameter_name = 'vence'

    def lookups(self, request, model_admin):
        return [('7', 'Activas que vencen en 7 días'), ('30', 'Activas que vencen en 30 días')]

    def queryset(self, request, queryset):
        if self.value():
            hoy = timezone.localdate()
            return queryset.filter(estado=Membresia.Estado.ACTIVA, fecha_inicio__lte=hoy,
                                   fecha_fin__range=(hoy, hoy + timedelta(days=int(self.value()))))
        return queryset


class CongelamientoInline(admin.TabularInline):
    model = Congelamiento
    extra = 0
    can_delete = False
    fields = ['fecha_inicio', 'ultimo_dia', 'dias', 'motivo', 'registrado_por']
    readonly_fields = fields
    verbose_name_plural = 'congelamientos (use la acción "Congelar" de la lista)'

    def has_add_permission(self, request, obj=None):
        return False


class MembresiaForm(forms.ModelForm):
    """Membresía de cortesía (sin pago) o corrección del término: no puede pisar otra del socio."""
    class Meta:
        model = Membresia
        fields = ['socio', 'plan', 'fecha_inicio', 'fecha_fin']

    def clean(self):
        datos = super().clean()
        socio, inicio, fin = datos.get('socio') or getattr(self.instance, 'socio', None), \
            datos.get('fecha_inicio') or self.instance.fecha_inicio, datos.get('fecha_fin')
        if socio and inicio and fin:
            if fin < inicio:
                raise ValidationError({'fecha_fin': 'El término no puede ser anterior al inicio.'})
            try:
                services.validar_traslape(socio.pk, inicio, fin, excluir_pk=self.instance.pk)
            except ErrorDeNegocio as e:
                raise ValidationError(e.mensaje)
        return datos


class CongelarForm(forms.Form):
    dias = forms.IntegerField(label='Días a congelar', min_value=1, max_value=365, initial=7)
    motivo = forms.CharField(label='Motivo', max_length=200, required=False)


@admin.register(Membresia)
class MembresiaAdmin(admin.ModelAdmin):
    form = MembresiaForm
    change_list_template = 'admin/membresias/membresia/change_list.html'
    list_display = ['socio', 'plan', 'fecha_inicio', 'fecha_fin', 'estado_etiqueta', 'restantes', 'pagada']
    list_filter = ['estado', PorVencerFiltro, 'plan', 'fecha_fin']
    search_fields = ['socio__usuario__first_name', 'socio__usuario__last_name', 'socio__usuario__rut']
    autocomplete_fields = ['socio']
    date_hierarchy = 'fecha_inicio'
    list_select_related = ['socio__usuario', 'plan', 'pago']
    list_per_page = 25
    inlines = [CongelamientoInline]
    actions = ['congelar', 'descongelar', 'actualizar_estados']

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ['estado']
        # una membresía existente solo cambia su término (corrección del administrador)
        return ['socio', 'plan', 'fecha_inicio', 'estado', 'pago_asociado']

    def get_fields(self, request, obj=None):
        if obj is None:
            return ['socio', 'plan', 'fecha_inicio', 'fecha_fin']
        return ['socio', 'plan', 'fecha_inicio', 'fecha_fin', 'estado', 'pago_asociado']

    def changelist_view(self, request, extra_context=None):
        services.sincronizar_estados()  # vencidas y descongeladas al día antes de mostrar la lista
        conteo = dict(Membresia.objects.values_list('estado').annotate(n=Count('id')))
        resumen = [{'estado': valor, 'texto': texto, 'cantidad': conteo.get(valor, 0)}
                   for valor, texto in Membresia.Estado.choices]
        return super().changelist_view(request, {**(extra_context or {}), 'resumen_estados': resumen})

    @admin.display(description='estado', ordering='estado')
    def estado_etiqueta(self, obj):
        return badge(obj.estado, obj.get_estado_display())

    @admin.display(description='días restantes')
    def restantes(self, obj):
        return obj.dias_restantes if obj.estado in services.VIGENTES else '-'

    @admin.display(description='pagada', boolean=True)
    def pagada(self, obj):
        return hasattr(obj, 'pago') and obj.pago.estado == Pago.Estado.PAGADO

    @admin.display(description='pago')
    def pago_asociado(self, obj):
        pago = getattr(obj, 'pago', None)
        return f'{pago.comprobante} · {pesos(pago.monto)} ({pago.get_estado_display()})' if pago else 'Cortesía (sin pago)'

    # Acción con página intermedia: primero pregunta los días y el motivo
    # (plantilla admin/membresias/membresia/congelar.html) y después congela.
    @admin.action(description='Congelar las membresías seleccionadas', permissions=['change'])
    def congelar(self, request, queryset):
        if 'aplicar' in request.POST:
            form = CongelarForm(request.POST)
            if form.is_valid():
                hechas = 0
                for membresia in queryset:
                    try:
                        services.congelar(membresia, form.cleaned_data['dias'], form.cleaned_data['motivo'],
                                          registrado_por=request.user)
                        hechas += 1
                    except ErrorDeNegocio as e:
                        self.message_user(request, f'{membresia.socio.nombre}: {e.mensaje}', messages.ERROR)
                if hechas:
                    self.message_user(request, f'{hechas} membresía(s) congelada(s) por {form.cleaned_data["dias"]} días.',
                                      messages.SUCCESS)
                return None
        else:
            form = CongelarForm()
        return TemplateResponse(request, 'admin/membresias/membresia/congelar.html', {
            **self.admin_site.each_context(request),
            'title': 'Congelar membresías',
            'membresias': queryset,
            'form': form,
            'opts': self.model._meta,
            'action_checkbox_name': ACTION_CHECKBOX_NAME,
        })

    @admin.action(description='Descongelar (reactivar hoy)', permissions=['change'])
    def descongelar(self, request, queryset):
        for membresia in queryset:
            try:
                services.descongelar(membresia)
                self.message_user(request, f'{membresia.socio.nombre}: membresía reactivada.', messages.SUCCESS)
            except ErrorDeNegocio as e:
                self.message_user(request, f'{membresia.socio.nombre}: {e.mensaje}', messages.ERROR)

    @admin.action(description='Actualizar estados por fecha (vencidas / fin de congelamiento)', permissions=['change'])
    def actualizar_estados(self, request, queryset):
        reactivadas, vencidas = services.sincronizar_estados()
        self.message_user(request, f'{vencidas} membresía(s) vencida(s) y {reactivadas} reactivada(s).', messages.INFO)


@admin.register(Congelamiento)
class CongelamientoAdmin(admin.ModelAdmin):
    list_display = ['membresia', 'fecha_inicio', 'ultimo_dia', 'dias', 'motivo', 'registrado_por']
    list_filter = ['fecha_inicio']
    search_fields = ['membresia__socio__usuario__first_name', 'membresia__socio__usuario__last_name', 'motivo']
    list_select_related = ['membresia__socio__usuario', 'membresia__plan', 'registrado_por']

    def has_add_permission(self, request):
        return False  # se congela con la acción de la lista de membresías

    def has_change_permission(self, request, obj=None):
        return False


class PagoForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = ['socio', 'plan', 'metodo', 'observacion']

    def clean_plan(self):
        plan = self.cleaned_data['plan']
        if not plan.activo:
            raise ValidationError(f'El plan "{plan}" no está a la venta.')
        return plan


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    form = PagoForm
    list_display = ['comprobante', 'fecha', 'socio', 'plan', 'monto_clp', 'metodo', 'estado_etiqueta',
                    'registrado_por']
    list_filter = ['estado', 'metodo', 'plan', 'fecha']
    search_fields = ['socio__usuario__first_name', 'socio__usuario__last_name', 'socio__usuario__rut']
    autocomplete_fields = ['socio']
    date_hierarchy = 'fecha'
    list_select_related = ['socio__usuario', 'plan', 'registrado_por']
    list_per_page = 25
    actions = ['anular']

    def get_fields(self, request, obj=None):
        if obj is None:
            return ['socio', 'plan', 'metodo', 'observacion']
        return ['comprobante', 'socio', 'plan', 'membresia', 'monto_clp', 'metodo', 'estado', 'fecha',
                'registrado_por', 'observacion', 'anulado_en', 'motivo_anulacion']

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        return ['comprobante', 'socio', 'plan', 'membresia', 'monto_clp', 'estado', 'fecha', 'registrado_por',
                'anulado_en', 'motivo_anulacion']

    def save_model(self, request, obj, form, change):
        if change:
            obj.save(update_fields=['metodo', 'observacion'])
        else:
            # registrar un pago crea la membresía (misma regla que la API)
            services.registrar_pago(obj.socio, obj.plan, obj.metodo, registrado_por=request.user,
                                    observacion=obj.observacion, pago=obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser  # los pagos se anulan, no se borran

    @admin.display(description='comprobante', ordering='id')
    def comprobante(self, obj):
        return obj.comprobante

    @admin.display(description='monto', ordering='monto')
    def monto_clp(self, obj):
        return pesos(obj.monto)

    @admin.display(description='estado', ordering='estado')
    def estado_etiqueta(self, obj):
        return badge(obj.estado, obj.get_estado_display())

    @admin.action(description='Anular los pagos seleccionados (cancela su membresía)', permissions=['change'])
    def anular(self, request, queryset):
        if not (request.user.is_superuser or request.user.rol == 'ADMIN'):
            self.message_user(request, 'Solo el administrador puede anular pagos.', messages.ERROR)
            return
        for pago in queryset:
            try:
                services.anular_pago(pago, f'Anulado desde el admin por {request.user.username}')
                self.message_user(request, f'{pago.comprobante} anulado.', messages.SUCCESS)
            except ErrorDeNegocio as e:
                self.message_user(request, f'{pago.comprobante}: {e.mensaje}', messages.ERROR)
