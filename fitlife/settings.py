"""
Configuración del proyecto fitlife (EVA-3 Backend).
Jorge Conejeros Suazo - TI3041 - 2026

Plataforma de control de asistencia y reserva de clases del centro
deportivo FitLife. Acá está todo lo global: la conexión a PostgreSQL, las
apps, DRF, las sesiones y la seguridad. Las claves y la contraseña de la
base se leen desde el archivo .env, que no se sube a GitHub.
"""
import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

from dotenv import load_dotenv

# Rutas del proyecto y lectura del .env.
# Si no existe el .env se usan los valores por defecto (solo para desarrollo).
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', 'clave-solo-para-desarrollo-cambiar')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
# en producción no se puede arrancar con la clave de desarrollo: con ella
# cualquiera podría firmar cookies de sesión y códigos QR válidos
if not DEBUG and SECRET_KEY == 'clave-solo-para-desarrollo-cambiar':
    raise ImproperlyConfigured('Falta SECRET_KEY en el .env (DEBUG=False).')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

# Para el despliegue en AWS (EC2 con Nginx delante de Gunicorn).
# CSRF_TRUSTED_ORIGINS lleva el dominio con https:// (ej. el de DuckDNS).
# Nginx avisa con X-Forwarded-Proto si la petición llegó por https, así
# Django sabe que la conexión es segura aunque Gunicorn la reciba en http.
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o]
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Sitio solo por HTTPS (en el servidor, con el certificado de certbot).
# Por defecto se activa cuando DEBUG=False; si la instancia se publica solo
# por IP, sin certificado, se pone HTTPS=False en el .env.
HTTPS = os.getenv('HTTPS', str(not DEBUG)) == 'True'
if HTTPS:
    SECURE_SSL_REDIRECT = True          # http -> https (Nginx también lo hace)
    SESSION_COOKIE_SECURE = True        # la cookie de sesión solo viaja por https
    CSRF_COOKIE_SECURE = True
    # HSTS: el navegador recuerda por 1 año que este dominio es solo https
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # preload pide registrar el dominio base (duckdns.org), que no es nuestro
    SILENCED_SYSTEM_CHECKS = ['security.W021']

# Content-Security-Policy (CSP): desde dónde puede cargar cosas el navegador.
# script-src sin 'unsafe-inline': un <script> en línea solo corre si trae el
# nonce de esta respuesta (nonce="{{ csp_nonce }}" en las plantillas, cambia
# en cada petición) y los onclick="..." no corren nunca (los botones usan
# data-accion, ver api.js). Del CDN se permiten solo las carpetas de las
# versiones que uso. jsQR es el lector de QR con la cámara.
CDN = 'https://cdn.jsdelivr.net/npm/'
BOOTSTRAP = CDN + 'bootstrap@5.3.3/'
ICONOS = CDN + 'bootstrap-icons@1.11.3/'
SWAGGER = CDN + 'swagger-ui-dist@5.34.0/'
JSQR = CDN + 'jsqr@1.4.0/'
SECURE_CSP = {
    'default-src': [CSP.SELF],
    'script-src': [CSP.SELF, BOOTSTRAP, SWAGGER, JSQR, CSP.NONCE],
    'script-src-attr': [CSP.NONE],
    'style-src': [CSP.SELF, BOOTSTRAP, ICONOS, SWAGGER, CSP.UNSAFE_INLINE],
    'font-src': [CSP.SELF, ICONOS],
    'img-src': [CSP.SELF, 'data:'],
    'connect-src': [CSP.SELF],
    'form-action': [CSP.SELF],
    'frame-ancestors': [CSP.NONE],      # nadie puede meter el sitio en un iframe
    'base-uri': [CSP.SELF],
    'object-src': [CSP.NONE],
}

# Apps instaladas.
# El admin va primero con mi configuración (core/apps.py), que cambia el
# sitio del admin por FitLifeAdminSite (portada con indicadores).
INSTALLED_APPS = [
    'core.apps.FitLifeAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Paquetes externos
    'rest_framework',
    'django_filters',
    'drf_spectacular',
    # Apps del proyecto
    'cuentas.apps.CuentasConfig',
    'membresias.apps.MembresiasConfig',
    'clases.apps.ClasesConfig',
    'accesos.apps.AccesosConfig',
    'core.apps.CoreConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.csp.ContentSecurityPolicyMiddleware',
    # errores de /api/ abiertos en el navegador -> plantillas del sitio
    'core.middleware.ErroresApiEnHtmlMiddleware',
]

ROOT_URLCONF = 'fitlife.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.csp',  # {{ csp_nonce }}
                'core.context_processors.rol',              # {{ rol }} para el menú
            ],
        },
    },
]

WSGI_APPLICATION = 'fitlife.wsgi.application'

# Base de datos PostgreSQL.
# El ENGINE postgresql usa por debajo el driver psycopg (versión 3). Los
# datos de conexión salen del .env para no dejar la contraseña en el código.
# En mi PC la base corre en Docker (puerto 5434); en la EC2, en el 5432.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'fitlife'),
        'USER': os.getenv('DB_USER', 'fitlife_app'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# Usuario propio en vez del User de Django: le agrego el rol y el RUT.
AUTH_USER_MODEL = 'cuentas.Usuario'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    # nivel de seguridad baja/media/alta/muy alta; la baja se rechaza
    {'NAME': 'cuentas.validadores.FortalezaPasswordValidator'},
]
# En las pruebas automáticas se usa un hash rápido: el PBKDF2 de verdad tarda
# ~0,5 s por contraseña y las pruebas crean muchos usuarios.
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Sesiones.
# El login guarda la sesión en la tabla django_session de PostgreSQL y el
# navegador solo recibe la cookie con el id (HttpOnly: el JavaScript no la
# puede leer). La sesión vence tras 1 hora sin actividad: cada petición
# renueva el plazo (SESSION_SAVE_EVERY_REQUEST).
SESSION_COOKIE_NAME = 'fitlife_sesion'
SESSION_COOKIE_AGE = 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
LOGIN_URL = 'login'

# Idioma y zona horaria de Chile
LANGUAGE_CODE = 'es-cl'
# fechas 27-10-2026 y miles con punto ($34.990), ver fitlife/formatos/es/formats.py
FORMAT_MODULE_PATH = ['fitlife.formatos']
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

# Archivos estáticos (css y js de las plantillas y del admin)
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Configuración de DRF.
# Autenticación por la sesión de Django (la misma cookie del login y del
# admin). Por defecto todo pide sesión iniciada; las vistas públicas, como
# los planes o el horario, lo cambian con sus propios permisos.
# Solo JSON: las páginas del sitio "enmascaran" la API (la consumen con fetch).
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'cuentas.autenticacion.SesionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
    'DEFAULT_CONTENT_NEGOTIATION_CLASS': 'fitlife.negociacion.NegociacionJSON',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'fitlife.paginacion.PaginacionEstandar',
    # las reglas del negocio rotas (clase cancelada, membresía vencida...) -> 400/409 con el motivo
    'EXCEPTION_HANDLER': 'core.excepciones.manejador_excepciones',
}

# Código QR dinámico de acceso: cada QR que muestra la app del socio vale
# 60 segundos (la página lo renueva cada 30). Ver accesos/qr.py.
QR_VIGENCIA_SEGUNDOS = int(os.getenv('QR_VIGENCIA_SEGUNDOS', '60'))

# Datos de la empresa para el encabezado del comprobante de pago (ficticios, para la evaluación)
EMPRESA = {
    'razon_social': 'FitLife Centro Deportivo SpA',
    'rut': '76.543.210-3',
    'giro': 'Gimnasios y centros de acondicionamiento físico',
    'direccion': 'Av. Providencia 1234, Providencia, Santiago',
    'telefono': '+56 2 2345 6789',
    'correo': 'contacto@fitlife.cl',
}

# Mis datos para la descripción de Swagger y el pie del admin
DATOS_ALUMNO = {
    'nombre': 'Jorge Conejeros Suazo',
    'seccion': 'TI3041',
    'anio': '2026',
}

# Swagger (drf-spectacular). La documentación queda en /api/docs/ (solo personal)
SPECTACULAR_SETTINGS = {
    'TITLE': 'API FitLife - Control de Asistencia y Reserva de Clases',
    'DESCRIPTION': (
        'API REST del centro deportivo FitLife: planes, pagos y membresías, control de acceso con QR, '
        'reserva de clases grupales con lista de espera y aforo en tiempo real.\n\n'
        'La API usa la **sesión de Django**: inicie sesión en `/login/` y esta página usa la misma cookie.\n\n'
        f"**Alumno:** {DATOS_ALUMNO['nombre']} · **Sección:** "
        f"{DATOS_ALUMNO['seccion']} · **Año:** {DATOS_ALUMNO['anio']}"
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'ENUM_NAME_OVERRIDES': {
        'EstadoMembresiaEnum': 'membresias.models.Membresia.Estado',
        'EstadoPagoEnum': 'membresias.models.Pago.Estado',
        'EstadoClaseEnum': 'clases.models.Clase.Estado',
        'EstadoReservaEnum': 'clases.models.Reserva.Estado',
        'MetodoPagoEnum': 'membresias.models.Pago.Metodo',
        'MetodoAccesoEnum': 'accesos.models.RegistroAcceso.Metodo',
    },
}
