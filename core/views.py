"""
Vistas HTML (el "enmascaramiento" de la API).

Estas vistas solo devuelven la plantilla con render(). Los datos los pide
después el JavaScript de cada página con fetch() a /api/... (con la cookie
de sesión y el token CSRF), y con eso arma las tablas.

La protección de las páginas va en el servidor: rol_requerido() manda al
login si no hay sesión y muestra la 403 si el rol no corresponde. Igual la
API revisa los permisos de nuevo en cada petición.
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve
from django.views.decorators.csrf import ensure_csrf_cookie

from cuentas.models import Usuario
from cuentas.permisos import rol_de
from cuentas.views import INICIO_POR_ROL

Rol = Usuario.Rol
STAFF = Usuario.ROLES_STAFF


def rol_requerido(*roles):
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if rol_de(request.user) not in roles:
                textos = ', '.join(Rol(r).label for r in roles)
                return render(request, '403.html', {'destino': request.path, 'rol_requerido': textos}, status=403)
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador


def pagina(plantilla, *roles):
    """Arma una vista que solo entrega la plantilla (con permiso por rol si se indica)."""
    @ensure_csrf_cookie
    def vista(request):
        return render(request, plantilla)
    return rol_requerido(*roles)(vista) if roles else vista


# públicas
inicio = pagina('web/inicio.html')
horario = pagina('web/horario.html')

# socio
mi_cuenta = pagina('web/socio.html', Rol.SOCIO)
mi_qr = pagina('web/mi_qr.html', Rol.SOCIO)

# instructor
instructor = pagina('web/instructor.html', Rol.INSTRUCTOR)

# recepción y administración
recepcion = pagina('web/recepcion.html', *STAFF)
aforo = pagina('web/aforo.html', *STAFF)
gestion_socios = pagina('web/gestion_socios.html', *STAFF)
gestion_pagos = pagina('web/gestion_pagos.html', *STAFF)
gestion_membresias = pagina('web/gestion_membresias.html', *STAFF)
gestion_planes = pagina('web/gestion_planes.html', *STAFF)
gestion_clases = pagina('web/gestion_clases.html', *STAFF)
api_docs = pagina('web/api_docs.html', *STAFF)


# comprobante de un pago: lo abre el personal o el socio dueño del pago
# (si un socio pone el id de otro pago, la API responde 404 y la página no muestra nada)
@rol_requerido(*STAFF, Rol.SOCIO)
def comprobante(request, pk):
    return render(request, 'web/comprobante.html', {'pago_id': pk, 'empresa': settings.EMPRESA})


@ensure_csrf_cookie
def login(request):
    # con la sesión ya iniciada no tiene sentido mostrar el login
    if request.user.is_authenticated:
        return redirect(INICIO_POR_ROL[rol_de(request.user)])
    return render(request, 'web/login.html')


@ensure_csrf_cookie
def registro(request):
    if request.user.is_authenticated:
        return redirect(INICIO_POR_ROL[rol_de(request.user)])
    return render(request, 'web/registro.html')


# Para cuando Django lanza PermissionDenied (o falla el CSRF de un formulario).
# En /api/ respondo JSON y en el resto la página 403.
def handler403(request, exception=None):
    if request.path.startswith('/api/'):
        return JsonResponse({'detail': 'No tiene permiso para realizar esta acción.'}, status=403)
    return render(request, '403.html', {'destino': request.path}, status=403)


# Error 404 controlado (lo llama la ruta comodín de urls.py, que funciona
# aunque DEBUG esté en True, y también handler404 cuando DEBUG=False).
def pagina_no_encontrada(request, exception=None):
    # si escribieron /horario sin la barra final y /horario/ existe, redirijo
    if not request.path.endswith('/'):
        try:
            if resolve(request.path + '/').func is not pagina_no_encontrada:
                return redirect(request.path + '/')
        except Resolver404:
            pass
    if request.path.startswith('/api/'):
        return JsonResponse(
            {'detail': f'El endpoint {request.path} no existe. Revise la documentación en /api/docs/.'}, status=404)
    return render(request, '404.html', {'ruta': request.path}, status=404)


def handler404(request, exception):
    return pagina_no_encontrada(request, exception)


# 400 y 500 propios (solo con DEBUG=False), así nunca sale la página de Django
def handler400(request, exception=None):
    if request.path.startswith('/api/'):
        return JsonResponse({'detail': 'Solicitud incorrecta.'}, status=400)
    return render(request, 'error.html', {'codigo': 400, 'titulo': 'Solicitud incorrecta'}, status=400)


def handler500(request):
    if request.path.startswith('/api/'):
        return JsonResponse({'detail': 'Error interno del servidor.'}, status=500)
    return render(request, 'error.html', {'codigo': 500, 'titulo': 'Error interno del servidor'}, status=500)
