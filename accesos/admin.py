"""
Admin de sedes, visitas y registros de acceso.

El historial de accesos es de solo lectura (auditoría): nadie lo puede
crear ni editar desde acá, y solo un superusuario puede borrar.
"""
from django.contrib import admin, messages

from core.admin_utils import badge, barra

from . import services
from .models import RegistroAcceso, Sede, Visita


@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'direccion', 'horario', 'aforo_ahora', 'aforo_maximo', 'activa']
    list_editable = ['aforo_maximo']
    search_fields = ['nombre']

    @admin.display(description='horario')
    def horario(self, obj):
        return f'{obj.hora_apertura:%H:%M} a {obj.hora_cierre:%H:%M}'

    @admin.display(description='aforo ahora')
    def aforo_ahora(self, obj):
        aforo = services.estado_aforo(obj)
        return barra(aforo['actual'], aforo['maximo'], f" · {aforo['porcentaje']}%")


class AbiertaFiltro(admin.SimpleListFilter):
    title = 'situación'
    parameter_name = 'situacion'

    def lookups(self, request, model_admin):
        return [('dentro', 'Dentro ahora'), ('cerrada', 'Ya salió')]

    def queryset(self, request, queryset):
        if self.value() == 'dentro':
            return queryset.filter(salida__isnull=True)
        if self.value() == 'cerrada':
            return queryset.filter(salida__isnull=False)
        return queryset


@admin.register(Visita)
class VisitaAdmin(admin.ModelAdmin):
    list_display = ['socio', 'sede', 'entrada', 'salida', 'duracion', 'dentro', 'cierre_automatico']
    list_filter = [AbiertaFiltro, 'sede', 'cierre_automatico', 'entrada']
    search_fields = ['socio__usuario__first_name', 'socio__usuario__last_name', 'socio__usuario__rut']
    date_hierarchy = 'entrada'
    list_select_related = ['socio__usuario', 'sede']
    readonly_fields = ['socio', 'sede', 'entrada', 'salida', 'cierre_automatico']
    actions = ['registrar_salida']

    def has_add_permission(self, request):
        return False  # las visitas las abre la lectura del QR

    @admin.display(description='tiempo dentro')
    def duracion(self, obj):
        horas, minutos = divmod(obj.minutos, 60)
        return f'{horas} h {minutos:02d} min' if horas else f'{minutos} min'

    @admin.display(description='dentro ahora', boolean=True)
    def dentro(self, obj):
        return obj.salida is None

    @admin.action(description='Registrar la salida ahora', permissions=['change'])
    def registrar_salida(self, request, queryset):
        abiertas = list(queryset.filter(salida__isnull=True))
        for visita in abiertas:
            services.registrar_salida_manual(visita, registrado_por=request.user)
        self.message_user(request, f'Salida registrada para {len(abiertas)} visita(s).', messages.SUCCESS)


@admin.register(RegistroAcceso)
class RegistroAccesoAdmin(admin.ModelAdmin):
    list_display = ['fecha_hora', 'socio', 'tipo', 'resultado_etiqueta', 'causa', 'metodo', 'registrado_por']
    list_filter = ['resultado', 'causa', 'tipo', 'metodo', 'sede', 'fecha_hora']
    search_fields = ['socio__usuario__first_name', 'socio__usuario__last_name', 'socio__usuario__rut', 'motivo']
    date_hierarchy = 'fecha_hora'
    list_select_related = ['socio__usuario', 'registrado_por', 'sede']
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description='resultado', ordering='resultado')
    def resultado_etiqueta(self, obj):
        return badge(obj.resultado, obj.get_resultado_display())
