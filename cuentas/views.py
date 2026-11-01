"""
Vistas de la API de cuentas: sesión (login, logout) y CRUD de socios.

POST /api/auth/login/    inicia la sesión de Django (cookie HttpOnly) · 5 fallos por IP = 10 min de bloqueo
POST /api/auth/registro/ crea una cuenta de socio e inicia su sesión · 5 cuentas por hora por IP
POST /api/auth/logout/   cierra la sesión (se borra de la tabla django_session)
GET  /api/auth/sesion/   quién soy, mi rol y cuándo vence mi sesión

/api/socios/        recepción y administración: listar, crear, ver, editar (desactivar)
/api/socios/{id}/qr/  el QR vigente del socio (para simular la lectura en recepción)
/api/instructores/  ver: con sesión (se crean y editan en el admin de Django)
"""
from django.contrib.auth import authenticate, login, logout
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from core.excepciones import ErrorDeNegocio
from membresias.models import Membresia
from membresias.services import sincronizar_estados

from . import bloqueo
from .autenticacion import SesionAuthentication
from .models import Instructor, Socio, Usuario
from .permisos import EsStaff, rol_de
from .serializers import (InstructorSerializer, LoginSerializer, RegistroSerializer, SesionSerializer,
                          SocioSerializer)

# a dónde va cada rol después del login
INICIO_POR_ROL = {
    Usuario.Rol.SOCIO: '/socio/',
    Usuario.Rol.INSTRUCTOR: '/instructor/',
    Usuario.Rol.RECEPCION: '/recepcion/',
    Usuario.Rol.ADMIN: '/aforo/',
}


class LoginView(APIView):
    """
    Login con la sesión de Django. authenticate() revisa la contraseña
    contra el hash guardado y login() crea la sesión (cambia el id de
    sesión, así no sirve uno robado antes del login). El login también
    exige el token CSRF, para que otro sitio no pueda iniciar sesión por
    el usuario. Frena la fuerza bruta igual que en la EVA-2.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=LoginSerializer, responses=SesionSerializer)
    def post(self, request):
        # DRF no revisa CSRF en peticiones sin sesión: lo exijo a mano
        SesionAuthentication().enforce_csrf(request)
        ip = bloqueo.ip_del_cliente(request)
        espera = bloqueo.segundos_de_bloqueo(ip)
        if espera:
            return self.respuesta_bloqueo(espera)

        datos = LoginSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        usuario = authenticate(request, **datos.validated_data)
        if usuario is None:
            # no digo si falló el usuario o la clave, para no revelar qué usuarios existen
            restantes, espera = bloqueo.registrar_fallo(ip)
            if espera:
                return self.respuesta_bloqueo(espera)
            texto = 'intento' if restantes == 1 else 'intentos'
            respuesta = Response({
                'detail': f'Usuario o contraseña incorrectos. Le quedan {restantes} {texto} antes de un bloqueo '
                          f'de {bloqueo.DURACION.seconds // 60} minutos.',
                'intentos_fallidos': bloqueo.MAX_FALLOS - restantes,
                'intentos_restantes': restantes,
            }, status=status.HTTP_401_UNAUTHORIZED)
            respuesta['WWW-Authenticate'] = 'Session realm="fitlife"'
            return respuesta

        bloqueo.limpiar(ip)
        login(request, usuario)
        datos = SesionSerializer(usuario, context={'request': request}).data
        return Response({**datos, 'inicio': INICIO_POR_ROL[rol_de(usuario)]})

    @staticmethod
    def respuesta_bloqueo(segundos):
        minutos = -(-segundos // 60)  # redondeo hacia arriba
        respuesta = Response({
            'detail': f'Demasiados intentos fallidos. Intente de nuevo en {minutos} minuto(s).',
            'intentos_fallidos': bloqueo.MAX_FALLOS,
            'intentos_restantes': 0,
            'segundos_bloqueo': segundos,
        }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        respuesta['Retry-After'] = str(segundos)
        return respuesta


class RegistroThrottle(AnonRateThrottle):
    """Límite de cuentas nuevas por IP (DEFAULT_THROTTLE_RATES['registro']), contra las cuentas falsas en masa."""
    scope = 'registro'

    def get_ident(self, request):
        return bloqueo.ip_del_cliente(request)  # la IP real que pone Nginx, no un X-Forwarded-For inventado


class RegistroView(APIView):
    """
    Registro público: cualquiera puede crear su cuenta, pero siempre queda
    como SOCIO y SIN membresía. Para entrar al gimnasio o reservar clases
    tiene que contratar un plan en recepción. Exige CSRF como el login y
    queda con la sesión iniciada.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [RegistroThrottle]

    @extend_schema(request=RegistroSerializer, responses={201: SesionSerializer})
    def post(self, request):
        SesionAuthentication().enforce_csrf(request)
        datos = RegistroSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        usuario = datos.save().usuario
        login(request, usuario)
        datos = SesionSerializer(usuario, context={'request': request}).data
        return Response({**datos, 'inicio': INICIO_POR_ROL[Usuario.Rol.SOCIO]}, status=status.HTTP_201_CREATED)

    def throttled(self, request, wait):
        raise Throttled(wait, detail='Se crearon demasiadas cuentas desde esta red.')


class LogoutView(APIView):
    """Cierra la sesión: logout() borra la sesión de la base y la cookie deja de servir."""
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={200: None})
    def post(self, request):
        logout(request)
        return Response({'detail': 'Sesión cerrada.'})


class SesionView(generics.RetrieveAPIView):
    serializer_class = SesionSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


# CRUD de socios (recepción y administración).
# No hay DELETE: un socio con historial se desactiva (activo=false), así
# no puede iniciar sesión ni entrar, pero sus pagos y accesos se conservan.
class SocioViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                   mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = SocioSerializer
    permission_classes = [EsStaff]
    filterset_fields = {'usuario__is_active': ['exact']}
    search_fields = ['usuario__first_name', 'usuario__last_name', 'usuario__rut', 'usuario__email',
                     'usuario__username']
    ordering_fields = ['usuario__last_name', 'fecha_alta']

    def get_queryset(self):
        return (Socio.objects.select_related('usuario')
                .prefetch_related(Prefetch('membresias', queryset=Membresia.objects.select_related('plan'))))

    def list(self, request, *args, **kwargs):
        sincronizar_estados()  # los estados que dependen de la fecha, al día antes de mostrarlos
        return super().list(request, *args, **kwargs)

    @extend_schema(responses={200: None})
    @action(detail=True)
    def qr(self, request, pk=None):
        """QR vigente del socio: recepción lo usa para simular la lectura."""
        from accesos import qr
        socio = self.get_object()
        if not socio.usuario.is_active:
            raise ErrorDeNegocio('El socio está desactivado: no tiene QR.')
        token = qr.generar_token(socio)
        return Response({'socio': socio.id, 'nombre': socio.nombre, 'codigo': token, 'imagen': qr.imagen_svg(token)})


class InstructorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Instructor.objects.select_related('usuario').filter(usuario__is_active=True)
    serializer_class = InstructorSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated]

