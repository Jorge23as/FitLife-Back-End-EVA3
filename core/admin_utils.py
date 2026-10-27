"""
Piezas visuales que comparten los admin de las apps: etiquetas de color
para los estados, montos en pesos y barras de ocupación.
format_html escapa los valores, así un nombre con HTML no se ejecuta.
"""
from django.utils.html import format_html

COLORES = {
    # membresías
    'ACTIVA': 'verde', 'VENCIDA': 'rojo', 'CONGELADA': 'azul', 'CANCELADA': 'gris', 'POR_COMENZAR': 'amarillo',
    'SIN_MEMBRESIA': 'gris',
    # pagos
    'PAGADO': 'verde', 'ANULADO': 'gris',
    # clases y reservas
    'PROGRAMADA': 'verde', 'CONFIRMADA': 'verde', 'ESPERA': 'amarillo', 'ASISTIO': 'azul', 'AUSENTE': 'rojo',
    # accesos
    'PERMITIDO': 'verde', 'DENEGADO': 'rojo',
    # roles
    'ADMIN': 'rojo', 'RECEPCION': 'azul', 'INSTRUCTOR': 'amarillo', 'SOCIO': 'verde',
}


def badge(valor, texto=None):
    return format_html('<span class="fl-badge fl-{}">{}</span>', COLORES.get(valor, 'gris'), texto or valor)


def pesos(monto):
    return f'${monto:,.0f}'.replace(',', '.')


def barra(ocupados, total, extra=''):
    porcentaje = min(100, round(ocupados * 100 / total)) if total else 0
    color = 'rojo' if porcentaje >= 100 else 'amarillo' if porcentaje >= 80 else 'verde'
    return format_html(
        '<div class="fl-barra" title="{}%"><div class="fl-barra-relleno fl-{}" style="width:{}%"></div></div>'
        '<small>{} / {}{}</small>', porcentaje, color, porcentaje, ocupados, total, extra)
