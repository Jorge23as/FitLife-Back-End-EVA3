"""
Serializers de planes, membresías y pagos.

Los que crean o cambian estados no lo hacen con save() directo: llaman a
services.py (registrar_pago, congelar, anular_pago), donde están las reglas.
"""
from datetime import timedelta

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.excepciones import ErrorDeNegocio
from cuentas.models import Socio

from . import services
from .models import Congelamiento, Membresia, Pago, Plan


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ['id', 'nombre', 'descripcion', 'precio', 'duracion_dias', 'incluye_clases', 'max_reservas_activas',
                  'dias_congelamiento', 'activo']


class CongelamientoSerializer(serializers.ModelSerializer):
    ultimo_dia = serializers.DateField(read_only=True)
    dias = serializers.IntegerField(read_only=True)
    registrado_por = serializers.CharField(source='registrado_por.nombre_completo', default=None, read_only=True)

    class Meta:
        model = Congelamiento
        fields = ['id', 'fecha_inicio', 'fecha_fin', 'ultimo_dia', 'dias', 'motivo', 'registrado_por', 'creado_en']


# Membresía. Lo normal es que la cree un pago (POST /api/pagos/); por acá el
# administrador puede crear una de cortesía (sin pago) o corregir el término.
# El estado no se escribe: cambia con las acciones congelar / descongelar,
# con la fecha (vencida) o al anular el pago (cancelada).
class MembresiaSerializer(serializers.ModelSerializer):
    socio_nombre = serializers.CharField(source='socio.nombre', read_only=True)
    socio_rut = serializers.CharField(source='socio.rut', read_only=True)
    plan_nombre = serializers.CharField(source='plan.nombre', read_only=True)
    estado_texto = serializers.CharField(source='get_estado_display', read_only=True)
    dias_restantes = serializers.IntegerField(read_only=True)
    dias_congelados = serializers.IntegerField(read_only=True)
    dias_congelamiento_plan = serializers.IntegerField(source='plan.dias_congelamiento', read_only=True)
    congelamientos = CongelamientoSerializer(many=True, read_only=True)
    pago = serializers.SerializerMethodField()
    fecha_inicio = serializers.DateField(required=False)
    fecha_fin = serializers.DateField(required=False, help_text='Vacío = inicio + duración del plan.')

    class Meta:
        model = Membresia
        fields = ['id', 'socio', 'socio_nombre', 'socio_rut', 'plan', 'plan_nombre', 'fecha_inicio', 'fecha_fin',
                  'estado', 'estado_texto', 'dias_restantes', 'dias_congelados', 'dias_congelamiento_plan',
                  'congelamientos', 'pago', 'creada_en']
        read_only_fields = ['estado', 'creada_en']

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_pago(self, membresia):
        pago = getattr(membresia, 'pago', None)
        return {'id': pago.id, 'comprobante': pago.comprobante, 'estado': pago.estado} if pago else None

    def validate(self, attrs):
        if self.instance:
            # al editar solo se corrige el término (el socio y el plan quedan como están)
            attrs = {'fecha_fin': attrs['fecha_fin']} if 'fecha_fin' in attrs else {}
            socio_id, plan, inicio = self.instance.socio_id, self.instance.plan, self.instance.fecha_inicio
        else:
            socio_id, plan = attrs['socio'].id, attrs['plan']
            inicio = attrs.setdefault('fecha_inicio', services.hoy())
        fin = attrs.get('fecha_fin') or getattr(self.instance, 'fecha_fin', None) or \
            inicio + timedelta(days=plan.duracion_dias - 1)
        if fin < inicio:
            raise serializers.ValidationError({'fecha_fin': 'El término no puede ser anterior al inicio.'})
        try:
            services.validar_traslape(socio_id, inicio, fin, excluir_pk=getattr(self.instance, 'pk', None))
        except ErrorDeNegocio as e:
            raise serializers.ValidationError({'fecha_fin': e.mensaje})
        attrs['fecha_fin'] = fin
        return attrs


class CongelarSerializer(serializers.Serializer):
    dias = serializers.IntegerField(min_value=1, max_value=365)
    motivo = serializers.CharField(max_length=200, required=False, allow_blank=True)


class PagoSerializer(serializers.ModelSerializer):
    comprobante = serializers.CharField(read_only=True)
    socio = serializers.PrimaryKeyRelatedField(queryset=Socio.objects.filter(usuario__is_active=True))
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all())
    socio_nombre = serializers.CharField(source='socio.nombre', read_only=True)
    socio_rut = serializers.CharField(source='socio.rut', read_only=True)
    plan_nombre = serializers.CharField(source='plan.nombre', read_only=True)
    metodo_texto = serializers.CharField(source='get_metodo_display', read_only=True)
    membresia_inicio = serializers.DateField(source='membresia.fecha_inicio', read_only=True)
    membresia_fin = serializers.DateField(source='membresia.fecha_fin', read_only=True)
    registrado_por = serializers.CharField(source='registrado_por.nombre_completo', default=None, read_only=True)

    class Meta:
        model = Pago
        fields = ['id', 'comprobante', 'socio', 'socio_nombre', 'socio_rut', 'plan', 'plan_nombre', 'membresia',
                  'membresia_inicio', 'membresia_fin', 'monto', 'metodo', 'metodo_texto', 'estado', 'fecha',
                  'registrado_por', 'observacion', 'anulado_en', 'motivo_anulacion']
        read_only_fields = ['membresia', 'monto', 'estado', 'fecha', 'anulado_en', 'motivo_anulacion']

    def create(self, validated_data):
        return services.registrar_pago(
            validated_data['socio'], validated_data['plan'], validated_data['metodo'],
            registrado_por=self.context['request'].user, observacion=validated_data.get('observacion', ''),
        )

    def update(self, instance, validated_data):
        # un pago registrado no cambia de socio, plan ni monto: solo se corrige el método o la observación
        for campo in ('metodo', 'observacion'):
            if campo in validated_data:
                setattr(instance, campo, validated_data[campo])
        instance.save(update_fields=['metodo', 'observacion'])
        return instance


class AnularPagoSerializer(serializers.Serializer):
    motivo = serializers.CharField(max_length=200)
