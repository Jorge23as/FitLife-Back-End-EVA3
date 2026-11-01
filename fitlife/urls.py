"""
Rutas principales del proyecto.

- /admin/     el admin de Django (personal: administración y recepción)
- /api/...    la API REST, que devuelve JSON (la consumen las páginas con fetch)
- /api/docs/  la documentación en Swagger (solo personal)
- /...        las páginas HTML del sitio
- al final, una ruta comodín que atrapa cualquier URL que no exista y
  muestra la 404 propia.
"""
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.routers import DefaultRouter

from accesos.views import AforoPublicoView, AforoView, MiQrView, RegistroAccesoViewSet, SedeViewSet, VisitaViewSet
from clases.views import ActividadViewSet, ClaseViewSet, ReservaViewSet, SalaViewSet
from core.api import MiCuentaView
from core.views import api_docs, pagina_no_encontrada
from cuentas.permisos import EsStaff
from cuentas.views import InstructorViewSet, LoginView, LogoutView, RegistroView, SesionView, SocioViewSet
from membresias.views import MembresiaViewSet, PagoViewSet, PlanViewSet

# El router crea las rutas del CRUD de cada ViewSet:
# /planes/ para listar y crear, /planes/<id>/ para ver, editar y borrar,
# y las acciones extra (/membresias/<id>/congelar/, /accesos/validar/...).
router = DefaultRouter()
router.register('planes', PlanViewSet, basename='plan')
router.register('membresias', MembresiaViewSet, basename='membresia')
router.register('pagos', PagoViewSet, basename='pago')
router.register('socios', SocioViewSet, basename='socio')
router.register('instructores', InstructorViewSet, basename='instructor')
router.register('actividades', ActividadViewSet, basename='actividad')
router.register('salas', SalaViewSet, basename='sala')
router.register('clases', ClaseViewSet, basename='clase')
router.register('reservas', ReservaViewSet, basename='reserva')
router.register('sedes', SedeViewSet, basename='sede')
router.register('accesos', RegistroAccesoViewSet, basename='acceso')
router.register('visitas', VisitaViewSet, basename='visita')

api_urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='api-login'),
    path('auth/registro/', RegistroView.as_view(), name='api-registro'),
    path('auth/logout/', LogoutView.as_view(), name='api-logout'),
    path('auth/sesion/', SesionView.as_view(), name='api-sesion'),
    path('mi-cuenta/', MiCuentaView.as_view(), name='api-mi-cuenta'),
    path('mi-qr/', MiQrView.as_view(), name='api-mi-qr'),
    path('aforo/', AforoView.as_view(), name='api-aforo'),
    path('aforo/publico/', AforoPublicoView.as_view(), name='api-aforo-publico'),
    # Documentación: solo personal (el esquema pide sesión de recepción o administración)
    path('schema/', SpectacularAPIView.as_view(permission_classes=[EsStaff]), name='schema'),
    path('docs/', api_docs, name='swagger-ui'),
    path('', include(router.urls)),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(api_urlpatterns)),
    path('', include('core.urls')),
    # Tiene que ir al final: si ninguna ruta de arriba calzó, cae acá
    re_path(r'^.*$', pagina_no_encontrada),
]

handler400 = 'core.views.handler400'
handler403 = 'core.views.handler403'
handler404 = 'core.views.handler404'
handler500 = 'core.views.handler500'
