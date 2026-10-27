"""
Código QR dinámico de cada socio.

El QR no lleva el RUT ni el id del socio: lleva su codigo_qr (un UUID
secreto) firmado con la SECRET_KEY y con la hora en que se generó
(TimestampSigner de Django). Al leerlo en la entrada se revisa:
  - la firma: que nadie lo haya inventado ni modificado, y
  - la antigüedad: vale QR_VIGENCIA_SEGUNDOS (60 s).
Así una captura de pantalla que se comparte con otra persona deja de
servir al minuto, y nadie puede entrar con el QR de un socio con la
membresía al día.

Contenido del QR:  FITLIFE:<uuid>:<hora>:<firma>
"""
import base64

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.core import signing

SAL = 'fitlife.accesos.qr'
PREFIJO = 'FITLIFE:'


class QrInvalido(Exception):
    def __init__(self, causa, motivo):
        super().__init__(motivo)
        self.causa = causa
        self.motivo = motivo


def _firmador():
    return signing.TimestampSigner(salt=SAL)


def generar_token(socio):
    return PREFIJO + _firmador().sign(str(socio.codigo_qr))


def leer_token(token):
    """Devuelve el codigo_qr del socio o lanza QrInvalido con la causa."""
    token = (token or '').strip()
    if not token.startswith(PREFIJO):
        raise QrInvalido('QR_INVALIDO', 'El código leído no es un QR de FitLife.')
    try:
        return _firmador().unsign(token[len(PREFIJO):], max_age=settings.QR_VIGENCIA_SEGUNDOS)
    except signing.SignatureExpired:
        raise QrInvalido('QR_EXPIRADO', 'QR expirado: el socio debe mostrar el QR actualizado de su app.')
    except signing.BadSignature:
        raise QrInvalido('QR_INVALIDO', 'QR no válido: la firma no corresponde (código alterado o inventado).')


def imagen_svg(texto):
    """El QR como imagen SVG lista para un <img src="..."> (data URI, sin archivos)."""
    imagen = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    return 'data:image/svg+xml;base64,' + base64.b64encode(imagen.to_string()).decode()
