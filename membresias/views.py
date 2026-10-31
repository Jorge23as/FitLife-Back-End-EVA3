"""
API de planes, membresías y pagos.

/api/planes/                  ver: cualquiera (los no-staff solo ven los planes a la venta) · modificar: administrador
/api/membresias/              recepción y administración · crear (cortesía), corregir término y borrar: administrador
/api/membresias/{id}/congelar/     POST {dias, motivo}   recepción y administración
/api/membresias/{id}/descongelar/  POST                  recepción y administración
/api/pagos/                   listar, ver y registrar: recepción y administración (el pago crea la membresía)
/api/pagos/{id}/              PATCH método u observación: administrador
/api/pagos/{id}/anular/       POST {motivo}: administrador (el pago no se borra, se anula)
/api/pagos/resumen/           recaudación de hoy y del mes
"""
from datetime import timedelta

import django_filters
from django.db.models import Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from cuentas.permisos import EsAdmin, EsSocio, EsStaff, LecturaPublicaEscrituraAdmin, rol_de
from cuentas.models import Usuario

from . import services
from .models import Membresia, Pago, Plan
from .serializers import (
    AnularPagoSerializer, CongelarSerializer, MembresiaSerializer, PagoSerializer, PlanSerializer,
)


class PlanViewSet(viewsets.ModelViewSet):
    serializer_class = PlanSerializer
    permission_classes = [LecturaPublicaEscrituraAdmin]
    pagination_class = None
    filterset_fields = ['activo', 'incluye_clases']
    search_fields = ['nombre']

    def get_queryset(self):
        if rol_de(self.request.user) in Usuario.ROLES_STAFF:
            return Plan.objects.all()
        return Plan.objects.filter(activo=True)


class MembresiaFiltro(django_filters.FilterSet):
    # ?por_vencer=7 -> activas que terminan dentro de los próximos 7 días
    por_vencer = django_filters.NumberFilter(method='filtrar_por_vencer', label='Activas que vencen en N días')

    class Meta:
        model = Membresia
        fields = ['estado', 'plan', 'socio']

    def filtrar_por_vencer(self, queryset, name, value):
        hoy = services.hoy()
        return queryset.filter(estado=Membresia.Estado.ACTIVA, fecha_inicio__lte=hoy,
                               fecha_fin__range=(hoy, hoy + timedelta(days=int(value))))


class MembresiaViewSet(viewsets.ModelViewSet):
    serializer_class = MembresiaSerializer
    filterset_class = MembresiaFiltro
    search_fields = ['socio__usuario__first_name', 'socio__usuario__last_name', 'socio__usuario__rut']
    ordering_fields = ['fecha_inicio', 'fecha_fin']
    queryset = (Membresia.objects.select_related('socio__usuario', 'plan', 'pago')
                .prefetch_related('congelamientos__registrado_por'))

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [EsAdmin()]
        return [EsStaff()]

    def list(self, request, *args, **kwargs):
        services.sincronizar_estados()
        return super().list(request, *args, **kwargs)

    @extend_schema(request=CongelarSerializer, responses=MembresiaSerializer)
    @action(detail=True, methods=['post'])
    def congelar(self, request, pk=None):
        datos = CongelarSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        membresia = services.congelar(self.get_object(), datos.validated_data['dias'],
                                      datos.validated_data.get('motivo', ''), registrado_por=request.user)
        return Response(self.get_serializer(self.get_queryset().get(pk=membresia.pk)).data)

    @extend_schema(request=None, responses=MembresiaSerializer)
    @action(detail=True, methods=['post'])
    def descongelar(self, request, pk=None):
        membresia = services.descongelar(self.get_object())
        return Response(self.get_serializer(self.get_queryset().get(pk=membresia.pk)).data)


class PagoFiltro(django_filters.FilterSet):
    desde = django_filters.DateFilter(field_name='fecha', lookup_expr='date__gte')
    hasta = django_filters.DateFilter(field_name='fecha', lookup_expr='date__lte')

    class Meta:
        model = Pago
        fields = ['metodo', 'estado', 'socio', 'plan']


# Sin DELETE: un pago no se borra, se anula (queda para la contabilidad)
class PagoViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                  mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = PagoSerializer
    filterset_class = PagoFiltro
    search_fields = ['socio__usuario__first_name', 'socio__usuario__last_name', 'socio__usuario__rut']
    ordering_fields = ['fecha', 'monto']
    queryset = Pago.objects.select_related('socio__usuario', 'plan', 'membresia', 'registrado_por')

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'anular'):
            return [EsAdmin()]
        if self.action == 'retrieve':
            return [(EsSocio | EsStaff)()]  # el socio puede abrir el comprobante de SUS pagos
        return [EsStaff()]

    def get_queryset(self):
        # un socio solo encuentra sus propios pagos: el de otro responde 404
        if rol_de(self.request.user) == Usuario.Rol.SOCIO:
            return self.queryset.filter(socio__usuario=self.request.user)
        return self.queryset

    @extend_schema(request=AnularPagoSerializer, responses=PagoSerializer)
    @action(detail=True, methods=['post'])
    def anular(self, request, pk=None):
        datos = AnularPagoSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        pago = services.anular_pago(self.get_object(), datos.validated_data['motivo'])
        return Response(self.get_serializer(self.get_queryset().get(pk=pago.pk)).data)

    @extend_schema(responses={200: None})
    @action(detail=False)
    def resumen(self, request):
        """Recaudación (pagos no anulados) de hoy y del mes, y cuánto por cada método."""
        ahora = timezone.localtime()
        pagados = Pago.objects.filter(estado=Pago.Estado.PAGADO)
        inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        mes = pagados.filter(fecha__gte=inicio_mes)
        totales = mes.aggregate(total_mes=Sum('monto', default=0), pagos_mes=Count('id'),
                                total_hoy=Sum('monto', default=0, filter=Q(fecha__date=ahora.date())),
                                pagos_hoy=Count('id', filter=Q(fecha__date=ahora.date())))
        metodos = dict(Pago.Metodo.choices)
        por_metodo = [{'metodo': fila['metodo'], 'texto': metodos[fila['metodo']], 'total': fila['total']}
                      for fila in mes.values('metodo').annotate(total=Sum('monto')).order_by('-total')]
        return Response({**totales, 'por_metodo': por_metodo})
