"""
Validadores de la app cuentas: fortaleza de contraseñas y RUT chileno.

Fortaleza (igual que en la EVA-2). Cada contraseña suma puntos (0 a 5):
  +1 tiene 8 caracteres o más
  +1 tiene 12 caracteres o más
  +1 mezcla minúsculas y mayúsculas
  +1 tiene números
  +1 tiene símbolos (!, #, $, ., -, etc.)

  0-2 puntos (o menos de 8 caracteres) -> Baja     (no se acepta)
  3 puntos                             -> Media    (aceptada)
  4 puntos                             -> Alta     (aceptada)
  5 puntos                             -> Muy alta (aceptada)
"""
import re

from django.core.exceptions import ValidationError

NIVELES = {0: 'Baja', 1: 'Baja', 2: 'Baja', 3: 'Media', 4: 'Alta', 5: 'Muy alta'}


def fortaleza(password):
    """Devuelve (puntos, nivel) de la contraseña."""
    puntos = 0
    puntos += len(password) >= 8
    puntos += len(password) >= 12
    puntos += any(c.islower() for c in password) and any(c.isupper() for c in password)
    puntos += any(c.isdigit() for c in password)
    puntos += any(not c.isalnum() for c in password)
    if len(password) < 8:
        puntos = min(puntos, 2)
    return puntos, NIVELES[puntos]


class FortalezaPasswordValidator:
    def validate(self, password, user=None):
        puntos, nivel = fortaleza(password)
        if nivel == 'Baja':
            raise ValidationError(
                'La contraseña es de seguridad baja. Use al menos 8 caracteres y combine mayúsculas, '
                'minúsculas, números y símbolos (nivel media o superior).',
                code='password_debil',
            )

    def get_help_text(self):
        return ('La contraseña debe tener seguridad media o superior: al menos 8 caracteres y combinar '
                'mayúsculas, minúsculas, números y símbolos.')


# RUT chileno. Lo dejo siempre igual antes de guardarlo: sin puntos ni
# espacios, con guion y la K en mayúscula (21.348.739-k -> 21348739-K).
# Así "21348739-k" y "21348739K" son el mismo RUT y el unique de la base
# los detecta como repetidos.
RUT_VALIDO = re.compile(r'^\d{1,8}-[\dK]$')


def normalizar_rut(valor):
    rut = re.sub(r'[\s.]', '', str(valor or '')).upper()
    if rut and '-' not in rut and len(rut) > 1:
        rut = f'{rut[:-1]}-{rut[-1]}'
    return rut


def digito_verificador(numero):
    """Dígito verificador con el algoritmo del módulo 11."""
    suma, factor = 0, 2
    for cifra in reversed(str(numero)):
        suma += int(cifra) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - suma % 11
    return {11: '0', 10: 'K'}.get(resto, str(resto))


def validar_rut(rut):
    """Recibe un RUT ya normalizado y lanza ValidationError si no es válido."""
    if not RUT_VALIDO.match(rut):
        raise ValidationError('El RUT debe tener el formato 12345678-9 (o terminar en K).')
    numero, dv = rut.split('-')
    if digito_verificador(numero) != dv:
        raise ValidationError('El RUT no es válido (el dígito verificador no corresponde).')
