"""
Admin de cuentas: usuarios (con rol), socios, instructores y bloqueos de login.
"""
from datetime import timedelta

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from django.utils.html import format_html

from accesos import qr
from core.admin_utils import badge, pesos
from membresias.models import Membresia, Pago
from membresias.services import congelada_el, situacion

from .models import BloqueoLogin, Instructor, Socio, Usuario
from .validadores import normalizar_rut, validar_rut


class RutFormMixin:
    def clean_rut(self):
        rut = normalizar_rut(self.cleaned_data.get('rut'))
        validar_rut(rut)
        return rut


class UsuarioCreacionForm(RutFormMixin, AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = Usuario
        fields = ('username', 'first_name', 'last_name', 'rut', 'email', 'telefono', 'rol')


class UsuarioCambioForm(RutFormMixin, UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    form = UsuarioCambioForm
    add_form = UsuarioCreacionForm
    list_display = ['username', 'nombre', 'rut', 'email', 'rol_etiqueta', 'is_active', 'last_login']
    list_filter = ['rol', 'is_active', 'is_superuser']
    search_fields = ['username', 'first_name', 'last_name', 'rut', 'email']
    ordering = ['last_name', 'first_name']
    list_per_page = 25
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Datos personales', {'fields': ('first_name', 'last_name', 'rut', 'email', 'telefono')}),
        ('Rol y acceso', {
            'fields': ('rol', 'is_active', 'is_superuser', 'grupo'),
            'description': 'El rol define el grupo de permisos. Administración y recepción entran a este admin; '
                           'instructores y socios usan el sitio.',
        }),
        ('Fechas', {'fields': ('last_login', 'date_joined'), 'classes': ('collapse',)}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'first_name', 'last_name', 'rut', 'email', 'telefono', 'rol', 'usable_password',
                       'password1', 'password2'),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        campos = ['last_login', 'date_joined', 'grupo']
        # solo un superusuario puede dar o quitar el superusuario (si no, un admin se lo daría a sí mismo)
        if not request.user.is_superuser:
            campos.append('is_superuser')
        return campos

    @admin.display(description='nombre', ordering='last_name')
    def nombre(self, obj):
        return obj.get_full_name()

    @admin.display(description='rol', ordering='rol')
    def rol_etiqueta(self, obj):
        return badge(obj.rol, obj.get_rol_display())

    @admin.display(description='grupo de permisos')
    def grupo(self, obj):
        return ', '.join(g.name for g in obj.groups.all()) or '-'


# --- Socios -----------------------------------------------------------------

class EstadoMembresiaFiltro(admin.SimpleListFilter):
    """Filtra a los socios por cómo está su membresía hoy."""
    title = 'membresía hoy'
    parameter_name = 'membresia'

    def lookups(self, request, model_admin):
        return [('ACTIVA', 'Activa'), ('POR_VENCER', 'Activa, vence en 7 días'), ('CONGELADA', 'Congelada'),
                ('SIN', 'Vencida o sin membresía')]

    def queryset(self, request, queryset):
        hoy = timezone.localdate()
        cubre = Membresia.objects.filter(socio=OuterRef('pk'), estado__in=['ACTIVA', 'CONGELADA'],
                                         fecha_inicio__lte=hoy, fecha_fin__gte=hoy)
        if self.value() == 'ACTIVA':
            return queryset.filter(Exists(cubre.filter(estado='ACTIVA')))
        if self.value() == 'POR_VENCER':
            return queryset.filter(Exists(cubre.filter(estado='ACTIVA', fecha_fin__lte=hoy + timedelta(days=7))))
        if self.value() == 'CONGELADA':
            return queryset.filter(Exists(cubre.filter(congelada_el(hoy))))
        if self.value() == 'SIN':
            return queryset.filter(~Exists(cubre))
        return queryset


class MembresiaInline(admin.TabularInline):
    model = Membresia
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ['plan', 'fecha_inicio', 'fecha_fin', 'estado_etiqueta']
    readonly_fields = fields
    verbose_name_plural = 'membresías (se crean al registrar un pago)'

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description='estado')
    def estado_etiqueta(self, obj):
        return badge(obj.estado, obj.get_estado_display())


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ['comprobante', 'fecha', 'plan', 'monto_clp', 'metodo', 'estado']
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description='monto')
    def monto_clp(self, obj):
        return pesos(obj.monto)


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'rut', 'email', 'membresia_hoy', 'vence', 'fecha_alta', 'activo']
    list_filter = [EstadoMembresiaFiltro, 'usuario__is_active', 'fecha_alta']
    search_fields = ['usuario__first_name', 'usuario__last_name', 'usuario__rut', 'usuario__email']
    list_select_related = ['usuario']
    list_per_page = 25
    date_hierarchy = 'fecha_alta'
    fieldsets = (
        ('Socio', {'fields': ('usuario', 'fecha_nacimiento', 'fecha_alta')}),
        ('Emergencias', {'fields': ('contacto_emergencia', 'telefono_emergencia')}),
        ('Acceso con QR', {
            'fields': ('membresia_actual', 'qr_vista_previa', 'codigo_qr'),
            'description': 'El QR cambia cada vez que se genera y vale 60 segundos. Si el socio pierde el celular, '
                           'use la acción "Regenerar código QR": los QR anteriores dejan de servir.',
        }),
    )
    readonly_fields = ['usuario', 'fecha_alta', 'codigo_qr', 'membresia_actual', 'qr_vista_previa']
    inlines = [MembresiaInline, PagoInline]
    actions = ['regenerar_qr']

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('membresias__plan')

    def has_add_permission(self, request):
        # el socio se crea al crear un Usuario con rol Socio (o desde Gestión de socios del sitio)
        return False

    @admin.display(description='nombre', ordering='usuario__last_name')
    def nombre(self, obj):
        return obj.nombre

    @admin.display(description='RUT', ordering='usuario__rut')
    def rut(self, obj):
        return obj.rut

    @admin.display(description='email')
    def email(self, obj):
        return obj.usuario.email

    @admin.display(description='membresía hoy')
    def membresia_hoy(self, obj):
        datos = situacion(obj)
        texto = f"{datos['texto']} · {datos['plan']}" if datos['plan'] else datos['texto']
        return badge(datos['estado'], texto)

    @admin.display(description='vence')
    def vence(self, obj):
        fin = situacion(obj)['fecha_fin']
        return fin.strftime('%d-%m-%Y') if fin else '-'

    @admin.display(description='activo', boolean=True, ordering='usuario__is_active')
    def activo(self, obj):
        return obj.usuario.is_active

    @admin.display(description='membresía')
    def membresia_actual(self, obj):
        datos = situacion(obj)
        if not datos['plan']:
            return badge(datos['estado'], datos['texto'])
        return format_html('{} {} · del {} al {} ({} días restantes)', badge(datos['estado'], datos['texto']),
                           datos['plan'], datos['fecha_inicio'].strftime('%d-%m-%Y'),
                           datos['fecha_fin'].strftime('%d-%m-%Y'), datos['dias_restantes'])

    @admin.display(description='QR de acceso (vista previa)')
    def qr_vista_previa(self, obj):
        if not obj.pk or not obj.usuario.is_active:
            return '-'
        return format_html('<img src="{}" alt="QR del socio" class="fl-qr">', qr.imagen_svg(qr.generar_token(obj)))

    @admin.action(description='Regenerar código QR (invalida los anteriores)', permissions=['change'])
    def regenerar_qr(self, request, queryset):
        for socio in queryset:
            socio.regenerar_qr()
        self.message_user(request, f'Se regeneró el QR de {queryset.count()} socio(s).', messages.SUCCESS)


@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'especialidad', 'email', 'clases_programadas']
    search_fields = ['usuario__first_name', 'usuario__last_name', 'especialidad']
    list_select_related = ['usuario']
    readonly_fields = ['usuario']

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            proximas=Count('clases', filter=Q(clases__inicio__gte=timezone.now(), clases__estado='PROGRAMADA')))

    def has_add_permission(self, request):
        return False  # se crea al crear un Usuario con rol Instructor

    @admin.display(description='nombre', ordering='usuario__first_name')
    def nombre(self, obj):
        return obj.nombre

    @admin.display(description='email')
    def email(self, obj):
        return obj.usuario.email

    @admin.display(description='clases próximas', ordering='proximas')
    def clases_programadas(self, obj):
        return obj.proximas


@admin.register(BloqueoLogin)
class BloqueoLoginAdmin(admin.ModelAdmin):
    list_display = ['ip', 'fallos', 'primer_fallo', 'bloqueado_hasta', 'bloqueada']
    search_fields = ['ip']
    readonly_fields = ['ip', 'fallos', 'primer_fallo', 'bloqueado_hasta']
    actions = ['desbloquear']

    def has_add_permission(self, request):
        return False

    @admin.display(description='bloqueada ahora', boolean=True)
    def bloqueada(self, obj):
        return bool(obj.bloqueado_hasta and obj.bloqueado_hasta > timezone.now())

    @admin.action(description='Desbloquear las IP seleccionadas', permissions=['delete'])
    def desbloquear(self, request, queryset):
        cantidad = queryset.count()
        queryset.delete()
        self.message_user(request, f'{cantidad} IP desbloqueada(s).', messages.SUCCESS)

