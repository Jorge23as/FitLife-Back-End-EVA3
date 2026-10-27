"""
Modelos de la app cuentas: Usuario (con rol), Socio, Instructor y
BloqueoLogin.

- Usuario hereda de AbstractUser (contraseña con hash, sesiones, grupos y
  permisos de Django) y le agrega el rol, el RUT y el teléfono.
- Lo que es solo del socio (fecha de nacimiento, contacto de emergencia y
  el código de su QR) va en Socio, y lo del instructor en Instructor, los
  dos 1:1 con Usuario. Así los usuarios que no son socios no quedan con
  columnas vacías (3FN).
"""
import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from .validadores import normalizar_rut


class UsuarioManager(UserManager):
    # python manage.py createsuperuser crea un administrador (no un socio)
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('rol', Usuario.Rol.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


# Usuario del sistema.
# El rol es un CHOICES con 4 opciones. Al guardar el usuario, el rol decide:
#  - is_staff: administración y recepción entran al admin de Django
#  - el grupo de Django (y con él los permisos del admin), ver roles.py
#  - el perfil: a un socio se le crea su Socio y a un instructor su Instructor
class Usuario(AbstractUser):

    class Rol(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrador'
        RECEPCION = 'RECEPCION', 'Recepción'
        INSTRUCTOR = 'INSTRUCTOR', 'Instructor'
        SOCIO = 'SOCIO', 'Socio'

    # roles del personal del gimnasio (entran al admin de Django)
    ROLES_STAFF = (Rol.ADMIN, Rol.RECEPCION)

    rol = models.CharField(max_length=12, choices=Rol.choices, default=Rol.SOCIO)
    rut = models.CharField('RUT', max_length=12, unique=True, help_text='Formato 12345678-9')
    telefono = models.CharField('teléfono', max_length=15, blank=True)

    objects = UsuarioManager()
    REQUIRED_FIELDS = ['email', 'first_name', 'last_name', 'rut']

    class Meta:
        verbose_name = 'usuario'
        verbose_name_plural = 'usuarios'
        ordering = ['last_name', 'first_name']

    def save(self, *args, **kwargs):
        self.rut = normalizar_rut(self.rut)
        self.is_staff = self.is_superuser or self.rol in self.ROLES_STAFF
        super().save(*args, **kwargs)
        # el login guarda solo last_login (update_fields): ahí no hay nada que sincronizar
        campos = kwargs.get('update_fields')
        if campos is None or 'rol' in campos:
            from .roles import sincronizar_grupo
            sincronizar_grupo(self)
            if self.rol == self.Rol.SOCIO:
                Socio.objects.get_or_create(usuario=self)
            elif self.rol == self.Rol.INSTRUCTOR:
                Instructor.objects.get_or_create(usuario=self)

    @property
    def es_staff_fitlife(self):
        return self.is_superuser or self.rol in self.ROLES_STAFF

    @property
    def nombre_completo(self):
        return self.get_full_name() or self.username

    def __str__(self):
        return f'{self.nombre_completo} ({self.get_rol_display()})'


# Socio del gimnasio.
# codigo_qr es un UUID secreto que va firmado dentro del QR de acceso (ver
# accesos/qr.py). No es el id ni el RUT, así nadie puede adivinarlo; y si el
# socio pierde el celular se regenera y los QR anteriores dejan de servir.
class Socio(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='socio')
    fecha_nacimiento = models.DateField('fecha de nacimiento', null=True, blank=True)
    contacto_emergencia = models.CharField('contacto de emergencia', max_length=100, blank=True)
    telefono_emergencia = models.CharField('teléfono de emergencia', max_length=15, blank=True)
    codigo_qr = models.UUIDField('código QR', default=uuid.uuid4, unique=True, editable=False)
    fecha_alta = models.DateField('fecha de alta', auto_now_add=True)

    class Meta:
        verbose_name = 'socio'
        verbose_name_plural = 'socios'
        ordering = ['usuario__last_name', 'usuario__first_name']

    @property
    def nombre(self):
        return self.usuario.nombre_completo

    @property
    def rut(self):
        return self.usuario.rut

    def regenerar_qr(self):
        self.codigo_qr = uuid.uuid4()
        self.save(update_fields=['codigo_qr'])

    def __str__(self):
        return f'{self.nombre} ({self.rut})'


class Instructor(models.Model):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='instructor')
    especialidad = models.CharField(max_length=100, blank=True)
    biografia = models.TextField('biografía', blank=True)

    class Meta:
        verbose_name = 'instructor'
        verbose_name_plural = 'instructores'
        ordering = ['usuario__first_name', 'usuario__last_name']

    @property
    def nombre(self):
        return self.usuario.nombre_completo

    def __str__(self):
        return self.nombre


# Bloqueo del login por fuerza bruta (por IP), igual que en la EVA-2.
# Cada IP tiene una fila con sus intentos fallidos. Al quinto fallo dentro
# de 10 minutos la IP queda bloqueada 10 minutos. Un login correcto borra
# la fila. Va en la base (y no en memoria) porque gunicorn corre 3 workers
# y todos tienen que ver el mismo contador.
class BloqueoLogin(models.Model):
    ip = models.GenericIPAddressField(unique=True)
    fallos = models.PositiveSmallIntegerField(default=0)
    primer_fallo = models.DateTimeField()
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'bloqueo de login'
        verbose_name_plural = 'bloqueos de login'

    def __str__(self):
        return f'{self.ip} ({self.fallos} fallos)'
