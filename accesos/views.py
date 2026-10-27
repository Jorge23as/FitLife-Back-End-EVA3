"""
API del control de acceso y del aforo.

POST /api/accesos/validar/        recepción: valida la lectura de un QR {codigo, metodo, modo, sede}
GET  /api/accesos/                recepción: historial de accesos (?resultado=&causa=&socio=&desde=)
/api/visitas/                     recepción: quién está dentro (?abiertas=true)
POST /api/visitas/{id}/salida/    recepción: marca la salida de alguien que se fue sin pasar el QR
/api/sedes/                       ver: personal · modificar (aforo máximo, horario): administrador
GET  /api/aforo/                  recepción: todo el dashboard de aforo (la página lo pide cada 5 s)
GET  /api/aforo/publico/          cualquiera: cuánta gente hay (para que el socio vea si está lleno)
GET  /api/mi-qr/                  socio: su QR dinámico (vale 60 s)
"""
import django_filters
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.excepciones import ErrorDeNegocio
from cuentas.permisos import EsSocio, EsStaff, LecturaStaffEscrituraAdmin
from membresias.services import situacion

from . import qr, services
from .models import RegistroAcceso, Sede, Visita


class SedeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sede
        fields = ['id', 'nombre', 'direccion', 'aforo_maximo', 'hora_apertura', 'hora_cierre',
                  'horas_max_permanencia', 'activa']


class RegistroAccesoSerializer(serializers.ModelSerializer):
    socio_nombre = serializers.CharField(source='socio.nombre', default=None, read_only=True)
    causa_texto = serializers.CharField(source='get_causa_display', read_only=True)
    metodo_texto = serializers.CharField(source='get_metodo_display', read_only=True)
    registrado_por = serializers.CharField(source='registrado_por.nombre_completo', default=None, read_only=True)

    class Meta:
        model = RegistroAcceso
        fields = ['id', 'fecha_hora', 'sede', 'socio', 'socio_nombre', 'tipo', 'resultado', 'causa', 'causa_texto',
                  'motivo', 'metodo', 'metodo_texto', 'registrado_por']


class VisitaSerializer(serializers.ModelSerializer):
    socio_nombre = serializers.CharField(source='socio.nombre', read_only=True)
    minutos = serializers.IntegerField(read_only=True)

    class Meta:
        model = Visita
        fields = ['id', 'socio', 'socio_nombre', 'sede', 'entrada', 'salida', 'minutos', 'cierre_automatico']


class ValidarAccesoSerializer(serializers.Serializer):
    codigo = serializers.CharField(max_length=500, help_text='Texto leído del QR (FITLIFE:...)')
    metodo = serializers.ChoiceField(choices=RegistroAcceso.Metodo.choices, default=RegistroAcceso.Metodo.CAMARA)
    modo = serializers.ChoiceField(choices=['AUTO', 'ENTRADA', 'SALIDA'], default='AUTO',
                                   help_text='AUTO: si el socio está dentro es su salida; si no, su entrada.')
    sede = serializers.PrimaryKeyRelatedField(queryset=Sede.objects.filter(activa=True), required=False)


def sede_o_error(sede=None):
    sede = sede or services.sede_principal()
    if sede is None:
        raise ErrorDeNegocio('No hay una sede activa configurada (créela en el admin de Django).')
    return sede


class RegistroAccesoFiltro(django_filters.FilterSet):
    desde = django_filters.DateFilter(field_name='fecha_hora', lookup_expr='date__gte')
    hasta = django_filters.DateFilter(field_name='fecha_hora', lookup_expr='date__lte')

    class Meta:
        model = RegistroAcceso
        fields = ['sede', 'socio', 'tipo', 'resultado', 'causa', 'metodo']


class RegistroAccesoViewSet(viewsets.ReadOnlyModelViewSet):
    """El historial de accesos es solo de lectura: es la auditoría de la entrada."""
    serializer_class = RegistroAccesoSerializer
    permission_classes = [EsStaff]
    filterset_class = RegistroAccesoFiltro
    search_fields = ['socio__usuario__first_name', 'socio__usuario__last_name', 'socio__usuario__rut']
    queryset = RegistroAcceso.objects.select_related('socio__usuario', 'registrado_por')

    @extend_schema(request=ValidarAccesoSerializer, responses={200: None})
    @action(detail=False, methods=['post'])
    def validar(self, request):
        datos = ValidarAccesoSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        d = datos.validated_data
        registro, visita, membresia, reserva = services.validar_acceso(
            d['codigo'], sede_o_error(d.get('sede')), d['metodo'], registrado_por=request.user, modo=d['modo'])
        socio = registro.socio
        return Response({
            'permitido': registro.resultado == RegistroAcceso.Resultado.PERMITIDO,
            'tipo': registro.tipo,
            'causa': registro.causa,
            'motivo': registro.motivo,
            'fecha_hora': registro.fecha_hora,
            'registro': registro.id,
            'socio': {
                'id': socio.id, 'nombre': socio.nombre, 'rut': socio.rut,
                'membresia': situacion(socio),
            } if socio else None,
            'visita': VisitaSerializer(visita).data if visita else None,
            'clase_de_hoy': {
                'actividad': reserva.clase.actividad.nombre, 'sala': reserva.clase.sala.nombre,
                'inicio': reserva.clase.inicio, 'estado': reserva.get_estado_display(),
            } if reserva else None,
            'aforo': services.estado_aforo(registro.sede),
        })


class VisitaFiltro(django_filters.FilterSet):
    abiertas = django_filters.BooleanFilter(field_name='salida', lookup_expr='isnull', label='Solo las abiertas')

    class Meta:
        model = Visita
        fields = ['sede', 'socio', 'cierre_automatico']


class VisitaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = VisitaSerializer
    permission_classes = [EsStaff]
    filterset_class = VisitaFiltro
    queryset = Visita.objects.select_related('socio__usuario')

    @extend_schema(request=None, responses=VisitaSerializer)
    @action(detail=True, methods=['post'])
    def salida(self, request, pk=None):
        visita = services.registrar_salida_manual(self.get_object(), registrado_por=request.user)
        return Response(VisitaSerializer(visita).data)


class SedeViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.ListModelMixin,
                  viewsets.GenericViewSet):
    queryset = Sede.objects.all()
    serializer_class = SedeSerializer
    permission_classes = [LecturaStaffEscrituraAdmin]
    pagination_class = None


class AforoView(APIView):
    permission_classes = [EsStaff]

    @extend_schema(responses={200: None})
    def get(self, request):
        sede = sede_o_error(get_object_or_404(Sede, pk=request.query_params['sede'])
                            if 'sede' in request.query_params else None)
        return Response(services.panel_aforo(sede))


class AforoPublicoView(APIView):
    """Solo cuánta gente hay y el nivel (sin nombres): lo ve cualquiera."""
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={200: None})
    def get(self, request):
        sede = sede_o_error()
        return Response({'sede': sede.nombre, 'abierta': sede.abierta(), **services.estado_aforo(sede),
                         'actualizado': timezone.now()})


class MiQrView(APIView):
    """QR dinámico del socio. La página lo pide de nuevo cada 30 segundos."""
    permission_classes = [EsSocio]

    @extend_schema(responses={200: None})
    def get(self, request):
        socio = request.user.socio
        token = qr.generar_token(socio)
        return Response({'codigo': token, 'imagen': qr.imagen_svg(token), 'generado': timezone.now(),
                         'vigencia_segundos': settings.QR_VIGENCIA_SEGUNDOS})
