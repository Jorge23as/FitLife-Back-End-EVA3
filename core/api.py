"""
GET /api/mi-cuenta/  (socio): todo lo que ve el socio en "Mi cuenta" en una
sola petición: su membresía, sus próximas reservas (y si alguna subió de
la lista de espera), sus pagos y sus últimos accesos.
"""
from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from accesos.models import RegistroAcceso, Visita
from accesos.views import RegistroAccesoSerializer
from clases.models import Reserva
from clases.serializers import ReservaSerializer
from cuentas.permisos import EsSocio
from membresias.models import Membresia, Pago
from membresias.serializers import MembresiaSerializer, PagoSerializer
from membresias.services import sincronizar_estados, situacion


class MiCuentaView(APIView):
    permission_classes = [EsSocio]

    @extend_schema(responses={200: None})
    def get(self, request):
        socio = request.user.socio
        sincronizar_estados(socio)
        ahora = timezone.now()
        reservas = (Reserva.objects.filter(socio=socio, clase__fin__gt=ahora).exclude(estado=Reserva.Estado.CANCELADA)
                    .select_related('clase__actividad', 'clase__sala', 'clase__instructor__usuario')
                    .order_by('clase__inicio'))
        # reservas que subieron de la lista de espera en las últimas 24 horas (aviso en la página)
        promovidas = reservas.filter(promovida_en__gte=ahora - timedelta(hours=24), estado=Reserva.Estado.CONFIRMADA)
        canceladas = (Reserva.objects.filter(socio=socio, clase__inicio__gt=ahora, estado=Reserva.Estado.CANCELADA,
                                             cancelada_en__gte=ahora - timedelta(hours=24))
                      .exclude(motivo_cancelacion='Cancelada por el socio')
                      .select_related('clase__actividad', 'clase__sala', 'clase__instructor__usuario'))
        visita = Visita.objects.filter(socio=socio, salida__isnull=True).first()
        membresias = (Membresia.objects.filter(socio=socio).select_related('plan', 'pago')
                      .prefetch_related('congelamientos'))
        return Response({
            'socio': {'id': socio.id, 'nombre': socio.nombre, 'rut': socio.rut, 'email': socio.usuario.email,
                      'telefono': socio.usuario.telefono, 'fecha_alta': socio.fecha_alta},
            'membresia': situacion(socio),
            'membresias': MembresiaSerializer(membresias[:6], many=True).data,
            'reservas': ReservaSerializer(reservas, many=True).data,
            'avisos_promovidas': ReservaSerializer(promovidas, many=True).data,
            'avisos_canceladas': ReservaSerializer(canceladas, many=True).data,
            'pagos': PagoSerializer(Pago.objects.filter(socio=socio).select_related('plan', 'membresia')[:6],
                                    many=True).data,
            'accesos': RegistroAccesoSerializer(RegistroAcceso.objects.filter(socio=socio)[:8], many=True).data,
            'dentro_desde': visita.entrada if visita else None,
        })
