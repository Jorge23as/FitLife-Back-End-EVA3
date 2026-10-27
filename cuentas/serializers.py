"""
Serializers de cuentas: login, sesión, socios e instructores.
"""
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from membresias.services import situacion

from .models import Instructor, Socio, Usuario
from .validadores import normalizar_rut, validar_rut


# El username y el RUT son únicos en Usuario, pero el serializer es de
# Socio: al editar hay que excluir al usuario de ese socio (no al usuario
# que por casualidad tenga el mismo id que el socio).
class UnicoEnUsuario(UniqueValidator):
    def __init__(self, mensaje):
        super().__init__(Usuario.objects.all(), mensaje)

    def exclude_current_instance(self, queryset, instance):
        return queryset.exclude(pk=instance.usuario_id) if instance is not None else queryset


# Campo RUT: lo normaliza y valida el dígito verificador antes de revisar
# el unique, así "21.348.739-k" choca con un "21348739-K" ya guardado.
class RutField(serializers.CharField):

    def __init__(self, **kwargs):
        kwargs.setdefault('max_length', 12)
        kwargs['validators'] = [UnicoEnUsuario('Ya existe una persona registrada con ese RUT.')]
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        rut = normalizar_rut(super().to_internal_value(data))
        try:
            validar_rut(rut)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return rut


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={'input_type': 'password'}, trim_whitespace=False)


class SesionSerializer(serializers.ModelSerializer):
    """Datos del usuario con sesión iniciada (GET /api/auth/sesion/)."""
    nombre = serializers.CharField(source='nombre_completo')
    rol_texto = serializers.CharField(source='get_rol_display')
    sesion_expira = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = ['id', 'username', 'nombre', 'email', 'rol', 'rol_texto', 'is_staff', 'sesion_expira']

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_sesion_expira(self, usuario):
        request = self.context.get('request')
        return request.session.get_expiry_date() if request else None


# Socio con los datos de su usuario "aplanados" (nombre, RUT, email...).
# Al crear, el serializer crea el Usuario con rol SOCIO y el perfil Socio en
# una sola transacción. La contraseña es solo de escritura y se guarda con
# set_password (hash), nunca en texto plano.
class SocioSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='usuario.username', max_length=150,
                                     validators=[UnicodeUsernameValidator(), UnicoEnUsuario('Ese nombre de usuario ya existe.')])
    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'},
                                     trim_whitespace=False)
    first_name = serializers.CharField(source='usuario.first_name', max_length=150)
    last_name = serializers.CharField(source='usuario.last_name', max_length=150)
    email = serializers.EmailField(source='usuario.email')
    rut = RutField(source='usuario.rut')
    telefono = serializers.CharField(source='usuario.telefono', max_length=15, required=False, allow_blank=True)
    activo = serializers.BooleanField(source='usuario.is_active', required=False)
    nombre = serializers.CharField(read_only=True)
    membresia = serializers.SerializerMethodField()

    class Meta:
        model = Socio
        fields = ['id', 'username', 'password', 'first_name', 'last_name', 'nombre', 'email', 'rut', 'telefono',
                  'fecha_nacimiento', 'contacto_emergencia', 'telefono_emergencia', 'activo', 'fecha_alta',
                  'membresia']
        read_only_fields = ['fecha_alta']

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_membresia(self, socio):
        return situacion(socio)

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'La contraseña es obligatoria al crear un socio.'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        datos_usuario = validated_data.pop('usuario')
        password = validated_data.pop('password')
        usuario = Usuario(rol=Usuario.Rol.SOCIO, **datos_usuario)
        usuario.set_password(password)
        usuario.save()  # al guardar con rol SOCIO se crea su perfil Socio
        socio = usuario.socio
        for campo, valor in validated_data.items():
            setattr(socio, campo, valor)
        socio.save()
        return socio

    @transaction.atomic
    def update(self, instance, validated_data):
        datos_usuario = validated_data.pop('usuario', {})
        password = validated_data.pop('password', None)
        usuario = instance.usuario
        for campo, valor in datos_usuario.items():
            setattr(usuario, campo, valor)
        if password:
            usuario.set_password(password)
        usuario.save()
        return super().update(instance, validated_data)


class InstructorSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(read_only=True)
    email = serializers.EmailField(source='usuario.email', read_only=True)

    class Meta:
        model = Instructor
        fields = ['id', 'nombre', 'email', 'especialidad', 'biografia']
