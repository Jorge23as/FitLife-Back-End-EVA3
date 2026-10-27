"""
Serializers de actividades, salas, clases y reservas.
"""
import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from cuentas.models import Instructor, Socio

from .models import Actividad, Clase, Reserva, Sala


class ActividadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Actividad
        fields = ['id', 'nombre', 'descripcion', 'duracion_minutos', 'intensidad', 'color', 'activa']


class SalaSerializer(serializers.ModelSerializer):
    sede_nombre = serializers.CharField(source='sede.nombre', read_only=True)

    class Meta:
        model = Sala
        fields = ['id', 'nombre', 'capacidad', 'sede', 'sede_nombre']


# Clase con sus cupos. ocupados y en_espera vienen anotados en la consulta
# (n_ocupados y n_espera: COUNT en la base, sin una consulta por clase). Si quien pide es un socio,
# mi_reserva dice si ya tiene reserva en esa clase.
class ClaseSerializer(serializers.ModelSerializer):
    actividad = serializers.PrimaryKeyRelatedField(queryset=Actividad.objects.filter(activa=True))
    instructor = serializers.PrimaryKeyRelatedField(queryset=Instructor.objects.filter(usuario__is_active=True))
    actividad_nombre = serializers.CharField(source='actividad.nombre', read_only=True)
    color = serializers.CharField(source='actividad.color', read_only=True)
    intensidad = serializers.CharField(source='actividad.get_intensidad_display', read_only=True)
    instructor_nombre = serializers.CharField(source='instructor.nombre', read_only=True)
    sala_nombre = serializers.CharField(source='sala.nombre', read_only=True)
    estado_texto = serializers.CharField(source='get_estado_display', read_only=True)
    fin = serializers.DateTimeField(required=False, help_text='Vacío = inicio + duración de la actividad.')
    ocupados = serializers.IntegerField(source='n_ocupados', read_only=True)
    en_espera = serializers.IntegerField(source='n_espera', read_only=True)
    disponibles = serializers.SerializerMethodField()
    mi_reserva = serializers.SerializerMethodField()

    class Meta:
        model = Clase
        fields = ['id', 'actividad', 'actividad_nombre', 'color', 'intensidad', 'instructor', 'instructor_nombre',
                  'sala', 'sala_nombre', 'inicio', 'fin', 'cupo', 'estado', 'estado_texto', 'ocupados',
                  'en_espera', 'disponibles', 'mi_reserva']
        read_only_fields = ['estado']

    def get_disponibles(self, clase) -> int:
        return max(clase.cupo - clase.n_ocupados, 0)

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_mi_reserva(self, clase):
        reserva_id = getattr(clase, 'mi_reserva_id', None)
        if not reserva_id:
            return None
        estado = clase.mi_reserva_estado
        posicion = Reserva.objects.get(pk=reserva_id).posicion_espera() if estado == Reserva.Estado.ESPERA else None
        return {'id': reserva_id, 'estado': estado, 'posicion_espera': posicion}

    def validate(self, attrs):
        # las reglas de la clase están en Clase.clean() (las mismas del admin de Django)
        clase = copy.copy(self.instance) if self.instance else Clase()
        for campo, valor in attrs.items():
            setattr(clase, campo, valor)
        if 'inicio' in attrs and 'fin' not in attrs:
            clase.fin = None  # se recalcula con la duración de la actividad
        try:
            clase.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict)
        attrs['fin'] = clase.fin
        return attrs


class ReservaSerializer(serializers.ModelSerializer):
    clase = serializers.PrimaryKeyRelatedField(queryset=Clase.objects.all())
    socio = serializers.PrimaryKeyRelatedField(queryset=Socio.objects.all(), required=False,
                                               help_text='Solo recepción: reservar a nombre de un socio.')
    socio_nombre = serializers.CharField(source='socio.nombre', read_only=True)
    estado_texto = serializers.CharField(source='get_estado_display', read_only=True)
    posicion_espera = serializers.SerializerMethodField()
    actividad = serializers.CharField(source='clase.actividad.nombre', read_only=True)
    color = serializers.CharField(source='clase.actividad.color', read_only=True)
    inicio = serializers.DateTimeField(source='clase.inicio', read_only=True)
    fin = serializers.DateTimeField(source='clase.fin', read_only=True)
    sala = serializers.CharField(source='clase.sala.nombre', read_only=True)
    instructor = serializers.CharField(source='clase.instructor.nombre', read_only=True)
    clase_cancelada = serializers.SerializerMethodField()

    class Meta:
        model = Reserva
        fields = ['id', 'clase', 'socio', 'socio_nombre', 'estado', 'estado_texto', 'posicion_espera', 'actividad',
                  'color', 'inicio', 'fin', 'sala', 'instructor', 'clase_cancelada', 'creada_en', 'promovida_en',
                  'cancelada_en', 'motivo_cancelacion']
        read_only_fields = ['estado', 'creada_en', 'promovida_en', 'cancelada_en', 'motivo_cancelacion']

    def get_posicion_espera(self, reserva) -> int | None:
        return reserva.posicion_espera()

    def get_clase_cancelada(self, reserva) -> bool:
        return reserva.clase.estado == Clase.Estado.CANCELADA


class AsistenciaSerializer(serializers.Serializer):
    asistio = serializers.BooleanField()
