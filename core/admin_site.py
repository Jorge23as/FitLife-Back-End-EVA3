"""
Sitio del admin de Django personalizado.

Cambia los títulos y, en la portada (/admin/), agrega tarjetas con los
indicadores del día: aforo, membresías por estado, pagos y clases. La
plantilla es templates/admin/index.html (extiende la original del admin).
"""
from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, Q, Sum
from django.utils import timezone


class FitLifeAdminSite(admin.AdminSite):
    site_header = 'FitLife · Administración'
    site_title = 'FitLife Admin'
    index_title = 'Panel de administración'
    site_url = '/'
    enable_nav_sidebar = False  # las listas tienen muchas columnas: les dejo todo el ancho

    def index(self, request, extra_context=None):
        return super().index(request, {**(extra_context or {}), 'indicadores': indicadores()})


def indicadores():
    from accesos.services import estado_aforo, sede_principal
    from clases.models import Clase, Reserva
    from membresias.models import Membresia, Pago
    from membresias.services import sincronizar_estados

    sincronizar_estados()
    hoy = timezone.localdate()
    estados = Membresia.objects.aggregate(
        activas=Count('id', filter=Q(estado=Membresia.Estado.ACTIVA, fecha_inicio__lte=hoy)),
        congeladas=Count('id', filter=Q(estado=Membresia.Estado.CONGELADA)),
        vencidas=Count('id', filter=Q(estado=Membresia.Estado.VENCIDA)),
        por_vencer=Count('id', filter=Q(estado=Membresia.Estado.ACTIVA, fecha_inicio__lte=hoy,
                                        fecha_fin__range=(hoy, hoy + timedelta(days=7)))),
    )
    pagos_hoy = Pago.objects.filter(estado=Pago.Estado.PAGADO, fecha__date=hoy).aggregate(
        total=Sum('monto', default=0), cantidad=Count('id'))
    # los alias no pueden llamarse "reservas": taparían la relación que usa el filtro
    clases_hoy = Clase.objects.filter(inicio__date=hoy, estado=Clase.Estado.PROGRAMADA).aggregate(
        n_clases=Count('id', distinct=True),
        n_reservas=Count('reservas', filter=Q(reservas__estado__in=Reserva.OCUPAN_CUPO)),
        n_espera=Count('reservas', filter=Q(reservas__estado=Reserva.Estado.ESPERA)))
    sede = sede_principal()
    return {
        'aforo': {**estado_aforo(sede), 'sede': sede.nombre} if sede else None,
        'membresias': estados,
        'pagos_hoy': pagos_hoy,
        'clases_hoy': clases_hoy,
    }
