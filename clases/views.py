"""
API de clases grupales y reservas.

/api/actividades/  /api/salas/     ver: cualquiera · modificar: administrador
/api/clases/                       horario: público (?desde=&hasta=&actividad=&mias=1) · crear/editar/borrar: administrador
/api/clases/{id}/cancelar/         POST administrador: cancela la clase y sus reservas
/api/clases/{id}/asistentes/       GET recepción, administración o el instructor de la clase: confirmados y lista de espera
/api/reservas/                     socio: las suyas · instructor: las de sus clases · personal: todas
                                   POST {clase} reserva (CONFIRMADA o ESPERA según el cupo)
/api/reservas/{id}/cancelar/       POST socio (la suya) o personal: libera el cupo y sube el primero de la espera
/api/reservas/{id}/asistencia/     POST {asistio} instructor de la clase o personal: pasar lista
"""
import django_filters
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.excepciones import Conflicto
from cuentas.models import Usuario
from cuentas.permisos import EsAdmin, EsInstructor, EsSocio, EsStaff, LecturaPublicaEscrituraAdmin, rol_de

from . import services
from .models import Actividad, Clase, Reserva, Sala
from .serializers import (
    ActividadSerializer, AsistenciaSerializer, ClaseSerializer, ReservaSerializer, SalaSerializer,
)

Rol = Usuario.Rol


class ActividadViewSet(viewsets.ModelViewSet):
    queryset = Actividad.objects.all()
    serializer_class = ActividadSerializer
    permission_classes = [LecturaPublicaEscrituraAdmin]
    pagination_class = None
    filterset_fields = ['activa', 'intensidad']
    search_fields = ['nombre']


class SalaViewSet(viewsets.ModelViewSet):
    queryset = Sala.objects.select_related('sede')
    serializer_class = SalaSerializer
    permission_classes = [LecturaPublicaEscrituraAdmin]
    pagination_class = None
    filterset_fields = ['sede']


class ClaseFiltro(django_filters.FilterSet):
    desde = django_filters.DateFilter(field_name='inicio', lookup_expr='date__gte')
    hasta = django_filters.DateFilter(field_name='inicio', lookup_expr='date__lte')
    mias = django_filters.BooleanFilter(method='filtrar_mias', label='Solo mis clases (instructor)')

    class Meta:
        model = Clase
        fields = ['actividad', 'instructor', 'sala', 'estado']

    def filtrar_mias(self, queryset, name, value):
        usuario = self.request.user
        if value and rol_de(usuario) == Rol.INSTRUCTOR:
            return queryset.filter(instructor__usuario=usuario)
        return queryset


class ClaseViewSet(viewsets.ModelViewSet):
    serializer_class = ClaseSerializer
    filterset_class = ClaseFiltro
    search_fields = ['actividad__nombre', 'instructor__usuario__first_name', 'sala__nombre']
    ordering_fields = ['inicio']

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        if self.action == 'asistentes':
            return [(EsStaff | EsInstructor)()]
        return [EsAdmin()]

    def get_queryset(self):
        # n_ocupados y no "ocupados": ese nombre taparía el método Clase.ocupados() que usan los services
        consulta = (Clase.objects.select_related('actividad', 'sala', 'instructor__usuario')
                    .annotate(n_ocupados=Count('reservas', filter=Q(reservas__estado__in=Reserva.OCUPAN_CUPO)),
                              n_espera=Count('reservas', filter=Q(reservas__estado=Reserva.Estado.ESPERA)))
                    # con GROUP BY (los Count) Django no aplica el ordering del modelo: hay que pedirlo
                    .order_by('inicio'))
        usuario = self.request.user
        if rol_de(usuario) == Rol.SOCIO:
            mia = (Reserva.objects.filter(clase=OuterRef('pk'), socio__usuario=usuario)
                   .exclude(estado=Reserva.Estado.CANCELADA))
            consulta = consulta.annotate(mi_reserva_id=Subquery(mia.values('id')[:1]),
                                         mi_reserva_estado=Subquery(mia.values('estado')[:1]))
        # el horario muestra de hoy en adelante si no se pide un rango
        if self.action == 'list' and 'desde' not in self.request.query_params:
            hoy = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
            consulta = consulta.filter(fin__gte=hoy)
        return consulta

    def perform_create(self, serializer):
        clase = Clase(**serializer.validated_data)
        services.guardar_clase(clase)
        serializer.instance = self.get_queryset().get(pk=clase.pk)  # con los cupos contados

    def perform_update(self, serializer):
        clase = serializer.instance
        for campo, valor in serializer.validated_data.items():
            setattr(clase, campo, valor)
        services.guardar_clase(clase)  # si subió el cupo, entra gente de la lista de espera
        serializer.instance = self.get_queryset().get(pk=clase.pk)

    def destroy(self, request, *args, **kwargs):
        if self.get_object().reservas.exists():
            raise Conflicto('La clase tiene reservas: cancélela en vez de borrarla (así se avisa a los socios).')
        return super().destroy(request, *args, **kwargs)

    @extend_schema(request=None, responses=ClaseSerializer)
    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        canceladas = services.cancelar_clase(self.get_object())
        clase = self.get_queryset().get(pk=pk)
        return Response({**self.get_serializer(clase).data, 'reservas_canceladas': canceladas})

    @extend_schema(responses=ReservaSerializer(many=True))
    @action(detail=True)
    def asistentes(self, request, pk=None):
        clase = self.get_object()
        if rol_de(request.user) == Rol.INSTRUCTOR and clase.instructor.usuario_id != request.user.id:
            raise PermissionDenied('Solo puede ver la lista de sus propias clases.')
        reservas = (clase.reservas.exclude(estado=Reserva.Estado.CANCELADA)
                    .select_related('socio__usuario', 'clase__actividad', 'clase__sala', 'clase__instructor__usuario'))
        return Response(ReservaSerializer(reservas, many=True).data)


class ReservaFiltro(django_filters.FilterSet):
    futuras = django_filters.BooleanFilter(method='filtrar_futuras', label='Solo clases que no han terminado')

    class Meta:
        model = Reserva
        fields = ['estado', 'clase', 'socio']

    def filtrar_futuras(self, queryset, name, value):
        return queryset.filter(clase__fin__gt=timezone.now()) if value else queryset


class ReservaViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin,
                     viewsets.GenericViewSet):
    serializer_class = ReservaSerializer
    filterset_class = ReservaFiltro
    ordering_fields = ['creada_en', 'clase__inicio']
    ordering = ['clase__inicio']

    def get_permissions(self):
        if self.action == 'create':
            return [(EsSocio | EsStaff)()]
        if self.action == 'asistencia':
            return [(EsInstructor | EsStaff)()]
        return [IsAuthenticated()]

    def get_queryset(self):
        consulta = Reserva.objects.select_related('socio__usuario', 'clase__actividad', 'clase__sala',
                                                  'clase__instructor__usuario')
        usuario = self.request.user
        rol = rol_de(usuario)
        if rol == Rol.SOCIO:
            return consulta.filter(socio__usuario=usuario)
        if rol == Rol.INSTRUCTOR:
            return consulta.filter(clase__instructor__usuario=usuario)
        if rol in Usuario.ROLES_STAFF:
            return consulta
        return consulta.none()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if rol_de(request.user) == Rol.SOCIO:
            socio = request.user.socio  # un socio solo reserva para sí mismo
        else:
            socio = serializer.validated_data.get('socio')
            if socio is None:
                raise ValidationError({'socio': 'Indique el socio para el que reserva.'})
        reserva = services.reservar(socio, serializer.validated_data['clase'])
        return Response(self.get_serializer(reserva).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=ReservaSerializer)
    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        reserva = self.get_object()
        if rol_de(request.user) == Rol.INSTRUCTOR:
            raise PermissionDenied('El instructor no cancela reservas.')
        motivo = 'Cancelada por el socio' if rol_de(request.user) == Rol.SOCIO else 'Cancelada por recepción'
        reserva, promovidas = services.cancelar_reserva(reserva, motivo)
        return Response({**self.get_serializer(reserva).data,
                         'promovidas': [r.socio.nombre for r in promovidas]})

    @extend_schema(request=AsistenciaSerializer, responses=ReservaSerializer)
    @action(detail=True, methods=['post'])
    def asistencia(self, request, pk=None):
        datos = AsistenciaSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        reserva = services.marcar_asistencia(self.get_object(), datos.validated_data['asistio'])
        return Response(self.get_serializer(reserva).data)
